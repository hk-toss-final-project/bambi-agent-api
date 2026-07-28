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
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from croniter import CroniterBadCronError, croniter
from psycopg import AsyncConnection

from infrastructure.persistence.api import (
    GlobalCollectionSchedule,
    load_collection_schedules,
)
from shared.contracts import FeatureRequest, FeatureResult
from workers.api import worker_001

type DictRow = dict[str, Any]

# 정기 수집 스케줄을 구현한 Provider와 담당 기능 ID.
SCHEDULED_PROVIDERS = {
    "naver": "SCH-002",
    "gdelt": "SCH-003",
    "newsapi": "SCH-004",
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
    if not schedule.keywords:
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


async def _run_scheduled_collection(
    connection: AsyncConnection[DictRow],
    *,
    provider: str,
    database_url: str,
    credentials: CollectionCredentials,
    now: datetime,
    force: bool = False,
) -> list[CollectionScheduleResult]:
    """한 Provider의 정기 수집 스케줄을 판정하고 실행 차례인 것만 수집한다.

    SCH-002·SCH-003·SCH-004가 공유하는 구현이다. Source의 키워드는 하나씩
    따로 수집해 주제가 섞인 단일 질의가 되지 않게 하고, 키워드 하나가 실패해도
    같은 Source의 다른 키워드 수집을 막지 않는다.

    Args:
        connection: 스케줄 설정을 읽을 Agent DB 연결
        provider: 수집 Provider 이름 (naver, gdelt, newsapi)
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
        try:
            following_run_at = next_collection_run_at(
                schedule.schedule_cron, after=now
            )
        except (CroniterBadCronError, ValueError):
            following_run_at = None
        remaining = (
            None
            if schedule.daily_max_runs is None
            else schedule.daily_max_runs - schedule.runs_today
        )
        for keyword in schedule.keywords:
            if remaining is not None and remaining <= 0:
                results.append(
                    CollectionScheduleResult(
                        provider=provider,
                        source_key=schedule.source_key,
                        status="skipped",
                        keyword=keyword,
                        reason=(
                            f"오늘 실행 한도 {schedule.daily_max_runs}회를 "
                            "채웠습니다."
                        ),
                        next_run_at=following_run_at,
                    )
                )
                continue
            # 키워드를 하나씩 넘겨야 주제가 섞인 단일 질의가 되지 않는다.
            collected = await worker_001(
                database_url=database_url,
                keywords=[keyword],
                providers=[provider],
                limit_per_provider=schedule.limit_per_provider,
                language=schedule.language,
                naver_client_id=credentials.naver_client_id,
                naver_client_secret=credentials.naver_client_secret,
                gdelt_base_url=credentials.gdelt_base_url,
                news_api_key=credentials.news_api_key,
            )
            if remaining is not None:
                remaining -= 1
            results.append(
                CollectionScheduleResult(
                    provider=provider,
                    source_key=schedule.source_key,
                    status="completed",
                    keyword=keyword,
                    next_run_at=following_run_at,
                    results=collected,
                )
            )
    return results


async def sch_001(request: FeatureRequest) -> FeatureResult:
    """[SCH-001] RSS 수집 스케줄.

    RSS Source 수집 작업을 정기 등록한다.
    """
    raise NotImplementedError("[SCH-001] 기능 구현이 필요합니다.")


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
    return await _run_scheduled_collection(
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
    """
    return await _run_scheduled_collection(
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
    return await _run_scheduled_collection(
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
