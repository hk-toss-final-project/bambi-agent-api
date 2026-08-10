"""기능 구현 모듈.

SCH-001, SCH-002, SCH-003, SCH-004, SCH-005, SCH-006, SCH-007, SCH-008 기능의 실제 구현 위치를 제공한다.

SCH-002·SCH-003·SCH-004는 `agent.global_sources`에 등록된 수집 주기
(`schedule_cron`)·키워드·쿼터를 읽어, 실행할 차례가 된 Provider만 수집
Worker(WORKER-001)로 넘긴다. 즉 이 모듈은 "무엇을 언제 돌릴지"만 판단하고
실제 수집·저장은 Worker가 한다.

판정 순서는 ① Cron 기준 실행 시각 도달 ② 키워드 존재 ③ 일일 실행 한도다.
`force`는 ①만 건너뛴다. 무료 플랜 호출 한도가 있는 Provider(NewsAPI 등)를
수동 실행으로 소진하지 않기 위해 쿼터는 어떤 경우에도 지킨다.

**키워드는 하나씩 따로 수집한다.** 수집 Worker는 키워드 목록을 공백으로 이어
붙여 단일 검색어를 만들기 때문에(`global_source_collector.py`), 한 번에 여러
주제를 넘기면 "코스피 삼성전자" 같은 질의가 되어 0건으로 끝난다
(global-collection-scheduling-proposal.md §4.3 실측). 따라서 Source의
`keywords` 배열은 "한 질의"가 아니라 "각각 따로 돌릴 주제 목록"으로 다룬다.
`quota_policy.daily_max_runs`도 이 실행 단위(= 외부 API 호출 수)를 센다.

**관심 Topic은 라벨과 확장 검색어를 함께 돌린다.** 라벨 하나로만 검색하면 한
사건·한 기관이 수집 예산을 독식한다(2026-08-05 실측: '경제·금융' 10건 중 4건이
같은 세미나 기사, '우주·천문' 10건 중 8건이 지역 과학관 홍보). 검색어를 나누면
질의마다 상위권만 모이므로 같은 예산으로 다루는 사건 수가 는다.

라벨을 버리지 않고 함께 두는 이유는 **큐레이션 키워드가 부실한 Topic이 있기**
때문이다(같은 실측: '우주·천문'의 `화성`이 경기도 화성시 교통사고를, `NASA`가
한국어 기사 0건을 끌어왔다). 라벨 검색이 그런 Topic의 안전망 역할을 한다.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from croniter import CroniterBadCronError, croniter
from psycopg import AsyncConnection

from infrastructure.persistence.api import (
    CollectionTargetPlan,
    GlobalCollectionSchedule,
    load_collection_schedules,
)
from shared.contracts import FeatureRequest, FeatureResult
from workers.api import worker_001

type DictRow = dict[str, Any]

# 정기 수집 스케줄을 등록할 수 있는 Provider와 담당 기능 ID.
#
# 뉴스 Provider는 명세에 Provider별 스케줄 기능(SCH-001~004)이 있다. SNS는
# 스케줄 기능 ID가 명세에 없어 수집 기능 ID(COL-005)를 적어 둔다 — 판정·실행
# 규칙은 뉴스와 완전히 같고, 실행은 아래 공용 구현이 그대로 맡는다.
SCHEDULED_PROVIDERS = {
    "google_news": "SCH-001",
    "naver": "SCH-002",
    "gdelt": "SCH-003",
    "newsapi": "SCH-004",
    "youtube": "COL-005",
    "reddit": "COL-005",
}


@dataclass(frozen=True, slots=True)
class CollectionCredentials:
    """수집 Provider가 필요로 하는 자격 증명과 Endpoint 설정.

    실제 값은 Scheduler 진입점이 환경 변수(Settings)에서 읽어 주입한다.
    """

    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    gdelt_base_url: str | None = None
    news_api_key: str | None = None


@dataclass(frozen=True, slots=True)
class CollectionQuery:
    """수집 실행 단위 하나 — 검색어와 그 결과를 귀속할 Topic, 가져올 건수."""

    query: str
    limit: int
    target_key: str | None = None


def split_collection_budget(limit: int, keyword_count: int) -> tuple[int, int]:
    """Topic 하나의 수집 예산을 라벨 검색과 확장 검색어에 나눈다.

    총량은 늘리지 않는다. 본문 수집 처리량이 병목이라(Jina Reader 호출) 수집
    건수를 늘리면 본문 없는 문서만 쌓인다. 그래서 "더 모으기"가 아니라 "같은
    예산을 여러 질의에 나눠 쓰기"로 다룬다.

    Args:
        limit: 이 Topic에 배정된 총 수집 건수
        keyword_count: 함께 돌릴 확장 검색어 수

    Returns:
        (라벨 검색으로 가져올 건수, 확장 검색어 하나당 가져올 건수).
        확장 검색어가 없으면 두 번째 값이 0이다.
    """
    if limit <= 0:
        return 0, 0
    if keyword_count <= 0:
        return limit, 0
    # 라벨은 큐레이션 키워드가 부실한 Topic의 안전망이라 최소 1건은 남긴다.
    usable = min(keyword_count, max(1, limit - 1))
    # +2는 라벨 몫을 키워드 두 개 분량쯤 확보하려는 것이다. limit 10·키워드 6이면
    # 키워드당 1건, 라벨 4건이 되어 합이 정확히 10이 된다.
    per_keyword = max(1, limit // (usable + 2))
    label = max(1, limit - per_keyword * usable)
    return label, per_keyword


def plan_target_queries(
    target: CollectionTargetPlan, *, limit: int
) -> list[CollectionQuery]:
    """관심 Topic 하나를 라벨 검색과 확장 검색어 검색으로 펼친다.

    어느 검색어로 모았든 결과는 같은 `target_key`에 귀속시킨다. 그래야 사용자가
    고른 라벨로 리포트를 만들 때 확장 검색어로 모은 자료까지 찾을 수 있다
    (generation_runtime.load_report_context의 토픽 가산점 참고).

    Args:
        target: 수집할 차례가 된 Topic과 큐레이션 검색어
        limit: 이 Topic에 배정된 총 수집 건수

    Returns:
        실행할 검색 목록. 라벨 검색이 항상 맨 앞에 온다
    """
    label_limit, per_keyword = split_collection_budget(limit, len(target.keywords))
    queries = [
        CollectionQuery(
            query=target.query, limit=label_limit, target_key=target.target_key
        )
    ]
    if per_keyword <= 0:
        return queries
    usable = min(len(target.keywords), max(1, limit - 1))
    for keyword in target.keywords[:usable]:
        # 라벨과 글자가 같은 키워드는 같은 검색을 두 번 돌리는 셈이라 건너뛴다.
        if keyword.casefold() == target.query.casefold():
            continue
        queries.append(
            CollectionQuery(
                query=keyword, limit=per_keyword, target_key=target.target_key
            )
        )
    return queries


def plan_schedule_queries(schedule: GlobalCollectionSchedule) -> list[CollectionQuery]:
    """Source 스케줄 하나가 이번에 실행할 검색 목록을 만든다.

    Source 고정 키워드(`keywords`)는 Topic 귀속이 없으므로 예전처럼 하나씩
    그대로 돌린다. 관심 Topic(`targets`)만 라벨·확장 검색어로 펼친다.
    """
    queries = [
        CollectionQuery(query=keyword, limit=schedule.limit_per_provider)
        for keyword in schedule.keywords
    ]
    for target in schedule.targets:
        queries.extend(
            plan_target_queries(target, limit=schedule.limit_per_provider)
        )
    return queries


@dataclass(frozen=True, slots=True)
class CollectionScheduleResult:
    """수집 실행 단위 하나(Source × 키워드)의 판정과 실행 결과.

    키워드를 실행하지 못하고 Source 단위로 건너뛴 경우(주기 미도달 등)에는
    keyword가 None이다.
    """

    provider: str
    source_key: str | None
    status: Literal["completed", "skipped", "not_configured"]
    keyword: str | None = None
    reason: str | None = None
    next_run_at: datetime | None = None
    results: list[dict[str, object]] = field(default_factory=list)


def _as_aware(moment: datetime) -> datetime:
    """시각 비교를 위해 naive datetime을 UTC 기준으로 맞춘다."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def next_collection_run_at(
    schedule_cron: str, *, after: datetime
) -> datetime:
    """Cron 식과 기준 시각으로 다음 수집 실행 시각을 계산한다.

    Args:
        schedule_cron: Source에 등록된 Cron 식 (예: "0 */6 * * *")
        after: 다음 실행 시각을 찾을 기준 시각

    Returns:
        기준 시각 다음에 오는 실행 시각

    Raises:
        CroniterBadCronError: Cron 식을 해석할 수 없을 때
    """
    return croniter(schedule_cron, _as_aware(after)).get_next(datetime)


def _evaluate_schedule(
    schedule: GlobalCollectionSchedule, *, now: datetime, force: bool
) -> tuple[str | None, datetime | None]:
    """스케줄을 지금 실행해도 되는지 판정한다.

    일일 한도는 남은 호출 여유가 하나도 없을 때만 Source 전체를 건너뛴다.
    여유가 일부만 남았으면 남은 만큼 키워드를 수집하고 나머지를 건너뛴다.

    Args:
        schedule: 판정할 Source 스케줄 설정
        now: 판정 기준 시각
        force: True면 Cron 실행 시각 조건만 건너뛴다 (쿼터는 그대로 지킨다)

    Returns:
        건너뛸 사유와 다음 실행 시각. 실행해도 되면 사유가 None이다.
    """
    if schedule.last_started_at is None:
        # 한 번도 수집한 적 없는 Source는 첫 주기를 기다리지 않고 바로 채운다.
        next_run_at = None
    else:
        try:
            next_run_at = next_collection_run_at(
                schedule.schedule_cron, after=schedule.last_started_at
            )
        except (CroniterBadCronError, ValueError):
            return (
                f"schedule_cron을 해석할 수 없습니다: {schedule.schedule_cron}",
                None,
            )
        if not force and next_run_at > _as_aware(now):
            return "다음 실행 시각 전입니다.", next_run_at
    if not schedule.keywords and not schedule.targets:
        return "수집 키워드가 비어 있습니다.", next_run_at
    if (
        schedule.daily_max_runs is not None
        and schedule.runs_today >= schedule.daily_max_runs
    ):
        return (
            f"오늘 실행 한도 {schedule.daily_max_runs}회를 채웠습니다.",
            next_run_at,
        )
    return None, next_run_at


# 수동 실행(SCH-021)에서 한 번에 동시에 수집할 최대 검색 수.
#
# 순차로 돌리면 관심 Topic이 많은 taxonomy Source에서 외부 API 호출이 수십 번
# 직렬로 쌓여 HTTP 응답이 분 단위로 늦어진다(2026-08-07 실측:
# interest-taxonomy-google-news 수동 실행 한 번에 google_news RSS 74회 이상,
# 5분 초과로 클라이언트 타임아웃). 검색을 동시에 돌려 시간을 줄이되, 동시 호출
# 수를 제한해 google_news RSS의 429(rate limit)와 DB 연결 폭증을 막는다.
# worker_001은 검색마다 자체 DB 연결을 열고 닫으므로, 이 상수가 곧 동시 연결
# 수의 상한이 된다.
MANUAL_RUN_CONCURRENCY = 6


async def _collect_planned_query(
    schedule: GlobalCollectionSchedule,
    planned: CollectionQuery,
    *,
    database_url: str,
    credentials: CollectionCredentials,
    following_run_at: datetime | None,
    trigger_source: str = "schedule",
) -> CollectionScheduleResult:
    """검색 하나를 수집 Worker로 실행하고 완료 결과로 감싼다.

    키워드를 하나씩 넘겨야 주제가 섞인 단일 질의가 되지 않는다. 순차 실행과
    동시 실행이 같은 규칙으로 Worker를 호출하도록 이 헬퍼를 공유한다.
    """
    collected = await worker_001(
        database_url=database_url,
        keywords=[planned.query],
        providers=[schedule.provider],
        limit_per_provider=planned.limit,
        language=schedule.language,
        naver_client_id=credentials.naver_client_id,
        naver_client_secret=credentials.naver_client_secret,
        gdelt_base_url=credentials.gdelt_base_url,
        news_api_key=credentials.news_api_key,
        search_options=dict(schedule.search_options),
        # 실행 이력을 이 수집을 지시한 Source에 남긴다. Provider 이름으로
        # 되돌리면 Cron 주기·일일 한도 판정이 쓰는 "마지막 실행 시각"이
        # 엉뚱한 Source에 쌓인다(persist_collected_articles 주석 참고).
        source_key=schedule.source_key,
        # 확장 검색어로 모은 문서도 원래 Topic에 연결한다. 이게 없으면
        # 검색어 글자가 달라 연결이 끊기고, 그 Topic의 next_collection_at도
        # 갱신되지 않아 매 tick 재검색된다.
        target_key=planned.target_key,
        # 점검용 수동 실행은 일일 한도 집계에서 빠진다. 한도는 알아서 도는
        # 수집을 통제하는 장치이므로, 관리자가 지금 눌러 본 실행이 그날 정기
        # 수집 예산을 먹으면 안 된다.
        trigger_source=trigger_source,
    )
    return CollectionScheduleResult(
        provider=schedule.provider,
        source_key=schedule.source_key,
        status="completed",
        keyword=planned.query,
        next_run_at=following_run_at,
        results=collected,
    )


async def _collect_queries_concurrently(
    schedule: GlobalCollectionSchedule,
    planned_queries: list[CollectionQuery],
    *,
    database_url: str,
    credentials: CollectionCredentials,
    following_run_at: datetime | None,
    concurrency: int,
    trigger_source: str = "manual",
) -> list[CollectionScheduleResult]:
    """여러 검색을 동시에 수집한다. 동시 실행 수를 세마포어로 제한한다.

    `asyncio.gather`는 입력 순서대로 결과를 돌려주므로, 결과 순서는 순차 실행과
    같다. 검색 하나가 실패해도 다른 검색을 막지 않는 오류 격리는 worker_001이
    Provider별 결과에 오류를 담아 돌려주는 것으로 유지된다(예외로 던지지 않는다).
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _bounded(planned: CollectionQuery) -> CollectionScheduleResult:
        """세마포어로 동시 실행 수를 제한하며 검색 하나를 수집한다."""
        async with semaphore:
            return await _collect_planned_query(
                schedule,
                planned,
                database_url=database_url,
                credentials=credentials,
                following_run_at=following_run_at,
                trigger_source=trigger_source,
            )

    return list(
        await asyncio.gather(*(_bounded(planned) for planned in planned_queries))
    )


async def collect_schedule_keywords(
    schedule: GlobalCollectionSchedule,
    *,
    database_url: str,
    credentials: CollectionCredentials,
    now: datetime,
    enforce_daily_limit: bool = True,
    concurrency: int = 1,
) -> list[CollectionScheduleResult]:
    """실행하기로 정해진 Source 스케줄의 키워드를 하나씩 수집한다.

    실행 차례(Cron) 판정은 하지 않는다. 호출자가 이미 실행하기로 정한 스케줄을
    받아 수집만 하므로, 정기 실행(SCH-001~004)과 수동 실행(SCH-021)이 같은
    수집 규칙(키워드 분리·오류 격리)을 공유한다.

    일일 실행 한도는 정기 실행에서만 지킨다. 수동 실행(SCH-021)은 관리자가
    지금 결과를 보겠다고 명시한 요청이라 한도로 막지 않는다.

    `concurrency`가 1보다 크고 일일 한도를 세지 않는 실행(수동 실행)이면 검색을
    동시에 수집해 응답 지연을 줄인다. 한도를 세는 정기 실행은 남은 호출 수를
    순서대로 깎아야 하므로 concurrency 값과 무관하게 순차로 돈다.

    Args:
        schedule: 수집할 Source 스케줄 설정
        database_url: 수집 Worker가 사용할 Agent DB 연결 문자열
        credentials: Provider 자격 증명 묶음
        now: 다음 실행 시각 계산 기준 시각
        enforce_daily_limit: False면 일일 실행 한도를 무시하고 모두 수집한다
        concurrency: 한도를 세지 않는 실행에서 동시에 수집할 최대 검색 수

    Returns:
        키워드별 수집 결과 목록. 한도를 채운 키워드는 skipped로 남는다
    """
    try:
        following_run_at = next_collection_run_at(
            schedule.schedule_cron, after=now
        )
    except (CroniterBadCronError, ValueError):
        following_run_at = None
    remaining = (
        None
        if schedule.daily_max_runs is None or not enforce_daily_limit
        else schedule.daily_max_runs - schedule.runs_today
    )
    # 한도를 세지 않는 실행이 곧 수동 실행(SCH-021)이다. 실행 이력에는 남기되
    # 일일 한도 집계에서는 빠지도록 표시한다 — 한도는 알아서 도는 수집을 통제하는
    # 장치라, 관리자가 점검하려고 누른 실행이 그날 정기 수집 예산을 먹으면 안 된다.
    trigger_source = "schedule" if enforce_daily_limit else "manual"
    planned_queries = plan_schedule_queries(schedule)
    # 한도를 세지 않는 실행만 동시에 돌린다. 한도를 세는 정기 실행은 남은 호출
    # 수를 순서대로 깎아 초과분을 skipped로 남겨야 하므로 순차 경로를 지킨다.
    if remaining is None and concurrency > 1:
        return await _collect_queries_concurrently(
            schedule,
            planned_queries,
            database_url=database_url,
            credentials=credentials,
            following_run_at=following_run_at,
            concurrency=concurrency,
            trigger_source=trigger_source,
        )
    results: list[CollectionScheduleResult] = []
    for planned in planned_queries:
        if remaining is not None and remaining <= 0:
            results.append(
                CollectionScheduleResult(
                    provider=schedule.provider,
                    source_key=schedule.source_key,
                    status="skipped",
                    keyword=planned.query,
                    reason=(
                        f"오늘 실행 한도 {schedule.daily_max_runs}회를 채웠습니다."
                    ),
                    next_run_at=following_run_at,
                )
            )
            continue
        result = await _collect_planned_query(
            schedule,
            planned,
            database_url=database_url,
            credentials=credentials,
            following_run_at=following_run_at,
            trigger_source=trigger_source,
        )
        if remaining is not None:
            remaining -= 1
        results.append(result)
    return results


async def run_provider_collection_schedule(
    connection: AsyncConnection[DictRow],
    *,
    provider: str,
    database_url: str,
    credentials: CollectionCredentials,
    now: datetime,
    force: bool = False,
) -> list[CollectionScheduleResult]:
    """한 Provider의 정기 수집 스케줄을 판정하고 실행 차례인 것만 수집한다.

    Provider별 스케줄 기능(SCH-001~004)이 공유하는 구현이며, 스케줄 기능 ID가
    없는 SNS Provider(youtube·reddit)는 Scheduler가 이 함수를 직접 호출한다.
    Source의 키워드는 하나씩 따로 수집해 주제가 섞인 단일 질의가 되지 않게 하고,
    키워드 하나가 실패해도 같은 Source의 다른 키워드 수집을 막지 않는다.

    Args:
        connection: 스케줄 설정을 읽을 Agent DB 연결
        provider: 수집 Provider 이름 (SCHEDULED_PROVIDERS의 Key)
        database_url: 수집 Worker가 사용할 Agent DB 연결 문자열
        credentials: Provider 자격 증명 묶음
        now: 실행 시각 판정 기준
        force: True면 Cron 실행 시각 조건을 건너뛴다

    Returns:
        Source × 키워드별 판정·실행 결과 목록. 설정된 스케줄이 없으면
        not_configured 결과 하나를 담아 돌려준다.
    """
    if connection is None or not hasattr(connection, "execute"):
        raise ValueError("정기 수집에 DB connection이 필요합니다.")
    if not database_url:
        raise ValueError("정기 수집에 database_url이 필요합니다.")

    schedules = [
        schedule
        for schedule in await load_collection_schedules(connection)
        if schedule.provider == provider
    ]
    if not schedules:
        return [
            CollectionScheduleResult(
                provider=provider,
                source_key=None,
                status="not_configured",
                reason="schedule_cron이 설정된 활성 Source가 없습니다.",
            )
        ]

    results: list[CollectionScheduleResult] = []
    for schedule in schedules:
        skip_reason, next_run_at = _evaluate_schedule(
            schedule, now=now, force=force
        )
        if skip_reason is not None:
            results.append(
                CollectionScheduleResult(
                    provider=provider,
                    source_key=schedule.source_key,
                    status="skipped",
                    reason=skip_reason,
                    next_run_at=next_run_at,
                )
            )
            continue
        results.extend(
            await collect_schedule_keywords(
                schedule,
                database_url=database_url,
                credentials=credentials,
                now=now,
            )
        )
    return results


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sch_001(
    connection: AsyncConnection[DictRow],
    *,
    database_url: str,
    credentials: CollectionCredentials,
    now: datetime,
    force: bool = False,
) -> list[CollectionScheduleResult]:
    """[SCH-001] RSS 수집 스케줄.

    RSS Source 수집 작업을 정기 등록한다. 판정·실행 규칙은 SCH-002와 같다.

    여기서 말하는 RSS Source는 Google News RSS(`google_news`, COL-001)다.
    명세의 "RSS Source"는 임의의 피드 주소를 가리키지만 현재 구현된 RSS 기반
    Provider는 이것 하나이고, 피드 URL이 아니라 키워드로 검색한다는 점이
    다르다. 그래도 이 자리에 두는 편이 낫다고 판단했다 — 영문 키워드에서
    가장 정확한 Provider인데(2026-07-28 실측: 'Cloudflare' 수집 시 Naver는
    10건 중 관련 3건, google_news는 5건 전부 관련) 스케줄에서 빠져 있었기
    때문이다.

    다른 Provider보다 느리다. 기사 link가 Google 리다이렉트 주소라 원본 URL
    디코딩에 약 1.2초/건이 들어, 키워드 하나당 12초쯤 더 걸린다.
    """
    return await run_provider_collection_schedule(
        connection,
        provider="google_news",
        database_url=database_url,
        credentials=credentials,
        now=now,
        force=force,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sch_002(
    connection: AsyncConnection[DictRow],
    *,
    database_url: str,
    credentials: CollectionCredentials,
    now: datetime,
    force: bool = False,
) -> list[CollectionScheduleResult]:
    """[SCH-002] Naver API 수집 스케줄.

    Naver API 수집 작업을 정기 등록한다. 등록된 주기가 되면 Source의 키워드로
    수집 Worker를 실행하고, 아직 차례가 아니거나 일일 호출 한도를 채웠으면
    건너뛴 사유를 남긴다.
    """
    return await run_provider_collection_schedule(
        connection,
        provider="naver",
        database_url=database_url,
        credentials=credentials,
        now=now,
        force=force,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sch_003(
    connection: AsyncConnection[DictRow],
    *,
    database_url: str,
    credentials: CollectionCredentials,
    now: datetime,
    force: bool = False,
) -> list[CollectionScheduleResult]:
    """[SCH-003] GDELT 수집 스케줄.

    GDELT 수집 작업을 정기 등록한다. 판정·실행 규칙은 SCH-002와 같다.

    GDELT는 인증 없는 공개 API라 짧은 간격 반복 호출에 429를 돌려준다
    (2026-07-28 실측: 07:26:52 수집 성공, 3분 뒤 같은 키워드 재호출은 429).
    영구 차단이 아니라 rate limit이므로 정기 주기에서는 정상 동작하고,
    수동 점검을 몇 분 간격으로 반복할 때만 걸린다. 429가 나도 실패는 이
    Provider 안에 갇혀 같은 tick의 다른 Provider 수집은 그대로 끝난다.
    """
    return await run_provider_collection_schedule(
        connection,
        provider="gdelt",
        database_url=database_url,
        credentials=credentials,
        now=now,
        force=force,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sch_004(
    connection: AsyncConnection[DictRow],
    *,
    database_url: str,
    credentials: CollectionCredentials,
    now: datetime,
    force: bool = False,
) -> list[CollectionScheduleResult]:
    """[SCH-004] NewsAPI 수집 스케줄.

    NewsAPI 수집 작업을 정기 등록한다. 무료 플랜 호출 한도가 낮으므로
    Source의 `quota_policy.daily_max_runs` 설정을 반드시 함께 쓴다.
    """
    return await run_provider_collection_schedule(
        connection,
        provider="newsapi",
        database_url=database_url,
        credentials=credentials,
        now=now,
        force=force,
    )


async def sch_005(request: FeatureRequest) -> FeatureResult:
    """[SCH-005] DART 수집 스케줄.

    DART 수집 작업을 정기 등록한다.
    """
    raise NotImplementedError("[SCH-005] 기능 구현이 필요합니다.")


async def sch_006(request: FeatureRequest) -> FeatureResult:
    """[SCH-006] KRX 수집 스케줄.

    KRX 수집 작업을 정기 등록한다.
    """
    raise NotImplementedError("[SCH-006] 기능 구현이 필요합니다.")


async def sch_007(request: FeatureRequest) -> FeatureResult:
    """[SCH-007] GitHub 수집 스케줄.

    GitHub 수집 작업을 정기 등록한다.
    """
    raise NotImplementedError("[SCH-007] 기능 구현이 필요합니다.")


async def sch_008(request: FeatureRequest) -> FeatureResult:
    """[SCH-008] arXiv 수집 스케줄.

    arXiv 수집 작업을 정기 등록한다.
    """
    raise NotImplementedError("[SCH-008] 기능 구현이 필요합니다.")
