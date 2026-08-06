"""기능 구현 모듈.

SCH-017, SCH-018, SCH-019, SCH-020, SCH-021, SCH-022, SCH-023 기능의 실제 구현 위치를 제공한다.

SCH-017·018·019·020·022는 Service가 Agent의 정기 수집 주기를 조정하는 창구다.
수집 주기·키워드·쿼터는 `agent.global_sources` row가 소유하므로, 이 기능들은
그 row를 읽고 바꾼다. Scheduler는 tick마다 같은 row를 다시 읽으므로 변경은
서버 재시작 없이 다음 tick부터 반영된다.

SCH-021만 설정을 바꾸지 않고 수집을 직접 실행한다. 주기를 기다리지 않고 지금
결과를 보고 싶을 때(키워드 변경 직후 점검 등) 쓰는 경로이며, 수집 규칙 자체는
정기 실행과 같은 구현(`collection.collect_schedule_keywords`)을 공유한다.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from croniter import CroniterBadCronError, croniter
from psycopg import AsyncConnection

from infrastructure.persistence.api import (
    GlobalCollectionRunRecord,
    GlobalCollectionSchedule,
    load_collection_runs,
    load_collection_schedule,
    load_collection_schedules,
    set_collection_schedule_status,
    update_collection_schedule,
    upsert_collection_schedule,
)
from .collection import (
    SCHEDULED_PROVIDERS,
    CollectionCredentials,
    CollectionScheduleResult,
    collect_schedule_keywords,
    next_collection_run_at,
)
from shared.contracts import FeatureRequest, FeatureResult

type DictRow = dict[str, Any]


class UnknownCollectionScheduleError(LookupError):
    """지정한 source_key의 수집 스케줄이 없을 때 발생한다."""

    def __init__(self, source_key: str) -> None:
        """찾지 못한 source_key를 메시지에 담는다."""
        super().__init__(f"수집 스케줄을 찾을 수 없습니다: {source_key}")
        self.source_key = source_key


@dataclass(frozen=True, slots=True)
class CollectionScheduleView:
    """Service에 돌려주는 수집 스케줄 하나의 현재 상태."""

    source_key: str
    provider: str
    display_name: str
    status: str
    schedule_cron: str
    keywords: tuple[str, ...]
    language: str | None
    limit_per_provider: int
    daily_max_runs: int | None
    last_started_at: datetime | None
    runs_today: int
    next_run_at: datetime | None
    cron_valid: bool


def _to_view(schedule: GlobalCollectionSchedule) -> CollectionScheduleView:
    """스케줄 설정에 다음 실행 시각을 얹어 Service 응답 값으로 만든다.

    다음 실행 시각은 마지막 실행 시각을 기준으로 계산한다. 한 번도 실행하지
    않았으면 Scheduler가 첫 tick에 바로 수집하므로 None으로 둔다.
    """
    next_run_at: datetime | None = None
    cron_valid = bool(schedule.schedule_cron)
    if cron_valid:
        try:
            croniter(schedule.schedule_cron, datetime.now(UTC))
        except (CroniterBadCronError, ValueError):
            cron_valid = False
        else:
            if schedule.last_started_at is not None:
                next_run_at = next_collection_run_at(
                    schedule.schedule_cron, after=schedule.last_started_at
                )
    return CollectionScheduleView(
        source_key=schedule.source_key,
        provider=schedule.provider,
        display_name=schedule.display_name,
        status=schedule.status,
        schedule_cron=schedule.schedule_cron,
        keywords=schedule.keywords,
        language=schedule.language,
        limit_per_provider=schedule.limit_per_provider,
        daily_max_runs=schedule.daily_max_runs,
        last_started_at=schedule.last_started_at,
        runs_today=schedule.runs_today,
        next_run_at=next_run_at,
        cron_valid=cron_valid,
    )


def _validate_cron(schedule_cron: str) -> str:
    """Cron 식을 검증하고 앞뒤 공백을 제거해 돌려준다.

    잘못된 Cron이 DB에 들어가면 Scheduler가 해당 Source를 매 tick 건너뛰기만
    한다. 저장 전에 걸러 Service가 즉시 알 수 있게 한다.
    """
    trimmed = schedule_cron.strip()
    if not trimmed:
        raise ValueError("schedule_cron이 비어 있습니다.")
    try:
        croniter(trimmed, datetime.now(UTC))
    except (CroniterBadCronError, ValueError) as error:
        raise ValueError(f"schedule_cron을 해석할 수 없습니다: {trimmed}") from error
    return trimmed


def _validate_keywords(keywords: list[str]) -> list[str]:
    """키워드 목록의 공백을 정리하고 비어 있지 않은지 확인한다.

    키워드는 각각 따로 수집하는 주제 목록이다. 하나의 검색어로 이어 붙지
    않는다(SCH-002 구현 주석 참고).
    """
    cleaned = [keyword.strip() for keyword in keywords if keyword.strip()]
    if not cleaned:
        raise ValueError("수집 키워드가 하나 이상 필요합니다.")
    return cleaned


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sch_017(
    connection: AsyncConnection[DictRow],
    *,
    source_key: str,
    provider: str,
    schedule_cron: str,
    keywords: list[str],
    display_name: str | None = None,
    language: str | None = None,
    limit_per_provider: int | None = None,
    daily_max_runs: int | None = None,
) -> CollectionScheduleView:
    """[SCH-017] 스케줄 등록.

    새로운 정기 작업을 등록한다. 같은 source_key가 이미 있으면 설정을 덮어쓰고
    중지 상태였더라도 다시 활성화한다(멱등 등록).
    """
    if provider not in SCHEDULED_PROVIDERS:
        raise ValueError(
            f"정기 수집을 지원하지 않는 Provider입니다: {provider} "
            f"(가능: {', '.join(sorted(SCHEDULED_PROVIDERS))})"
        )
    stored = await upsert_collection_schedule(
        connection,
        source_key=source_key.strip(),
        provider=provider,
        display_name=display_name,
        schedule_cron=_validate_cron(schedule_cron),
        keywords=_validate_keywords(keywords),
        language=language,
        limit_per_provider=limit_per_provider,
        daily_max_runs=daily_max_runs,
    )
    return _to_view(stored)


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sch_018(
    connection: AsyncConnection[DictRow],
    *,
    source_key: str,
    schedule_cron: str | None = None,
    keywords: list[str] | None = None,
    language: str | None = None,
    limit_per_provider: int | None = None,
    daily_max_runs: int | None = None,
) -> CollectionScheduleView:
    """[SCH-018] 스케줄 수정.

    기존 작업의 실행 주기를 변경한다. 넘기지 않은 항목은 기존 값을 유지한다.
    변경은 Scheduler의 다음 tick부터 반영되며 서버 재시작이 필요 없다.
    """
    updated = await update_collection_schedule(
        connection,
        source_key=source_key,
        schedule_cron=(
            None if schedule_cron is None else _validate_cron(schedule_cron)
        ),
        keywords=None if keywords is None else _validate_keywords(keywords),
        language=language,
        limit_per_provider=limit_per_provider,
        daily_max_runs=daily_max_runs,
    )
    if updated is None:
        raise UnknownCollectionScheduleError(source_key)
    return _to_view(updated)


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sch_019(
    connection: AsyncConnection[DictRow], *, source_key: str
) -> CollectionScheduleView:
    """[SCH-019] 스케줄 중지.

    정기 작업 실행을 일시 중지한다. 설정은 그대로 두고 status만 paused로 바꿔,
    재개할 때 주기·키워드를 다시 입력하지 않아도 되게 한다.
    """
    paused = await set_collection_schedule_status(
        connection, source_key=source_key, status="paused"
    )
    if paused is None:
        raise UnknownCollectionScheduleError(source_key)
    return _to_view(paused)


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sch_020(
    connection: AsyncConnection[DictRow], *, source_key: str
) -> CollectionScheduleView:
    """[SCH-020] 스케줄 재개.

    중지된 정기 작업을 다시 활성화한다.
    """
    resumed = await set_collection_schedule_status(
        connection, source_key=source_key, status="active"
    )
    if resumed is None:
        raise UnknownCollectionScheduleError(source_key)
    return _to_view(resumed)


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sch_021(
    connection: AsyncConnection[DictRow],
    *,
    source_key: str,
    database_url: str,
    credentials: CollectionCredentials,
    now: datetime | None = None,
) -> tuple[CollectionScheduleView, list[CollectionScheduleResult]]:
    """[SCH-021] 스케줄 수동 실행.

    관리자가 정기 작업을 즉시 실행한다. 등록된 Cron 주기와 무관하게 지금 한 번
    수집하므로, 키워드를 바꾸고 다음 tick까지 기다리지 않고 결과를 확인할 수
    있다.

    **정기 실행 조건에 걸리지 않는다.** Cron 주기, 일일 실행 한도
    (`quota_policy.daily_max_runs`), 중지(paused) 상태를 모두 건너뛴다. 이
    조건들은 "알아서 도는 수집"을 통제하는 장치이고, 수동 실행은 관리자가 지금
    결과를 보겠다고 명시한 별개 행위이기 때문이다. 실행하면 키워드는 항상 전부
    수집한다.

    다만 이 실행도 `global_collection_runs`에 기록되므로, 이후 정기 실행의
    오늘 실행 횟수(`runs_today`)에는 그대로 반영된다.

    Args:
        connection: 스케줄 설정을 읽을 Agent DB 연결
        source_key: 즉시 실행할 Source 식별 Key
        database_url: 수집 Worker가 사용할 Agent DB 연결 문자열
        credentials: Provider 자격 증명 묶음
        now: 다음 실행 시각 계산 기준 시각 (미지정 시 현재 UTC)

    Returns:
        실행 후 스케줄 상태와 키워드별 수집 결과 목록

    Raises:
        UnknownCollectionScheduleError: 등록되지 않은 source_key일 때
        ValueError: 정기 수집을 지원하지 않는 Provider일 때
    """
    schedule = await load_collection_schedule(connection, source_key=source_key)
    if schedule is None:
        raise UnknownCollectionScheduleError(source_key)
    if schedule.provider not in SCHEDULED_PROVIDERS:
        raise ValueError(
            f"정기 수집을 지원하지 않는 Provider입니다: {schedule.provider} "
            f"(가능: {', '.join(sorted(SCHEDULED_PROVIDERS))})"
        )
    moment = now or datetime.now(UTC)
    # 관심 Topic(targets)도 검색어가 된다. 고정 키워드만 보면, 검색어를 전부
    # 관심 Topic으로 받는 스케줄(interest-taxonomy-google-news)이 "키워드가 비어
    # 있다"며 건너뛴다 — 정기 실행은 멀쩡히 돌던 스케줄이라 더 헷갈린다. 정기
    # 실행(collection.should_run_schedule)과 같은 조건을 쓴다.
    if not schedule.keywords and not schedule.targets:
        return (
            _to_view(schedule),
            [
                CollectionScheduleResult(
                    provider=schedule.provider,
                    source_key=schedule.source_key,
                    status="skipped",
                    reason="수집 키워드가 비어 있습니다.",
                )
            ],
        )
    results = await collect_schedule_keywords(
        schedule,
        database_url=database_url,
        credentials=credentials,
        now=moment,
        enforce_daily_limit=False,
    )
    # 실행 직후 상태(마지막 실행 시각·오늘 실행 횟수)를 다시 읽어 돌려준다.
    refreshed = await load_collection_schedule(connection, source_key=source_key)
    return _to_view(refreshed or schedule), results


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sch_022(
    connection: AsyncConnection[DictRow],
    *,
    source_key: str | None = None,
    history_limit: int = 20,
) -> tuple[list[CollectionScheduleView], list[GlobalCollectionRunRecord]]:
    """[SCH-022] 스케줄 이력 조회.

    스케줄별 실행 결과와 상태를 조회한다. 주기가 아직 없거나 중지된 Source도
    함께 반환해, Service가 조정할 대상을 목록에서 바로 찾을 수 있게 한다.
    """
    schedules = await load_collection_schedules(connection, only_scheduled=False)
    if source_key is not None:
        schedules = [
            schedule for schedule in schedules if schedule.source_key == source_key
        ]
        if not schedules:
            raise UnknownCollectionScheduleError(source_key)
    runs = await load_collection_runs(
        connection, source_key=source_key, limit=history_limit
    )
    return [_to_view(schedule) for schedule in schedules], runs


async def sch_023(request: FeatureRequest) -> FeatureResult:
    """[SCH-023] 실패 스케줄 재실행.

    실패한 정기 작업을 다시 실행한다.
    """
    raise NotImplementedError("[SCH-023] 기능 구현이 필요합니다.")
