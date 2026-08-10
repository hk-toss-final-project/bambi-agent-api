"""기능 구현 모듈.

SCH-009, SCH-010 기능의 실제 구현 위치를 제공한다.

SCH-009는 수집으로 누적된 personal_wiki_build Job의 실행 시각을
조용 시간(quiet window)과 최대 대기시간 정책으로 조정한다.

SCH-010은 관심사 Profile이 오래된 사용자를 주기적으로 다시 계산한다.
관심사 점수는 계산 시각 기준으로 최신성을 감쇠시키므로, 저장이 멈춘 사용자는
재계산이 돌지 않으면 마지막 Build 시점 점수에 그대로 고정된다.

정기 Wiki 재구성 등록(`schedule_personal_wiki_maintenance_rebuilds`)은 명세
기능 ID가 없는 유지보수 단계다. 증분 Build가 원본 유입에만 반응해 누적된
중복·고아 문서를 정리할 기회가 없으므로, 재구성을 시계로 돌린다.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any, Literal

from psycopg import AsyncConnection

from domain.interests.api import ActiveWikiRequiredError, int_011
from infrastructure.persistence.api import (
    ConnectionInterestProfileRepository,
    defer_user_wiki_build_jobs,
    enqueue_personal_wiki_maintenance_rebuild_job,
    list_users_for_interest_recalculation,
    list_users_for_maintenance_rebuild,
    release_user_wiki_build_jobs,
    sync_wiki_interest_collection_targets,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WikiScheduleResult:
    """SCH-009 Wiki Build 실행 시각 조정 결과."""

    action: Literal["defer", "release"]
    affected_jobs: int


async def sch_009(
    connection: AsyncConnection[dict[str, Any]],
    *,
    user_id: str,
    action: Literal["defer", "release"] = "defer",
    quiet_minutes: int = 10,
    max_wait_minutes: int = 30,
) -> WikiScheduleResult:
    """[SCH-009] 사용자 Wiki 재구성 스케줄.

    변경이 누적된 사용자의 대기 Wiki Build Job 실행 시각을 조정한다.
    action이 "defer"면 마지막 수집 기준 quiet_minutes만큼 미루되 첫 대기
    Job 기준 max_wait_minutes를 넘지 않게 하고, "release"면 사용자의
    강제 실행 요청으로 모든 대기 Job을 즉시 실행 가능하게 만든다.
    """
    if connection is None or not hasattr(connection, "execute"):
        raise ValueError("SCH-009에 DB connection이 필요합니다.")
    if not user_id:
        raise ValueError("SCH-009에 user_id가 필요합니다.")
    if action not in ("defer", "release"):
        raise ValueError("SCH-009의 action은 defer 또는 release여야 합니다.")
    if quiet_minutes < 0 or max_wait_minutes < 1:
        raise ValueError("SCH-009의 대기시간 설정이 허용 범위를 벗어났습니다.")
    if action == "defer":
        affected = await defer_user_wiki_build_jobs(
            connection,
            user_id=user_id,
            quiet_minutes=quiet_minutes,
            max_wait_minutes=max_wait_minutes,
        )
    else:
        affected = await release_user_wiki_build_jobs(
            connection,
            user_id=user_id,
        )
    return WikiScheduleResult(action=action, affected_jobs=affected)


@dataclass(frozen=True, slots=True)
class InterestRecalculationResult:
    """SCH-010이 사용자 한 명의 관심사를 재계산한 결과."""

    user_id: str
    status: Literal["completed", "skipped", "failed"]
    version: int | None = None
    interest_count: int = 0
    subscribed_targets: tuple[str, ...] = ()
    reason: str | None = None


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sch_010(
    connection: AsyncConnection[dict[str, Any]],
    *,
    stale_after_hours: float = 24.0,
    limit: int = 50,
    now: datetime | None = None,
) -> list[InterestRecalculationResult]:
    """[SCH-010] 사용자 관심사 재계산.

    개인 Wiki 변경에 따라 관심사 프로필을 재계산한다. Profile이 오래된
    사용자만 골라 INT-011을 다시 돌리므로, 저장 활동이 없어도 시간 감쇠가
    실제 점수에 반영된다. 재계산에 성공하면 상위 관심사를 창고 수집 대상으로
    함께 갱신한다.

    사용자 한 명의 실패가 나머지 재계산을 막지 않도록 사용자 단위로 격리한다.

    Args:
        connection: 이미 열린 agent-db 커넥션
        stale_after_hours: 이 시간이 지난 Profile만 재계산한다
        limit: 한 번의 실행에서 처리할 최대 사용자 수
        now: 판정 기준 시각 (미지정 시 현재 UTC)

    Returns:
        처리한 사용자별 재계산 결과 목록 (대상이 없으면 빈 목록)
    """
    users = await list_users_for_interest_recalculation(
        connection,
        stale_after_hours=stale_after_hours,
        limit=limit,
        now=now,
    )
    results: list[InterestRecalculationResult] = []
    for user_id in users:
        try:
            repository = ConnectionInterestProfileRepository(connection)
            profile = await int_011(repository, user_id)
        except ActiveWikiRequiredError as error:
            # 조회와 재계산 사이에 Wiki가 초기화된 경우다. 실패가 아니다.
            results.append(
                InterestRecalculationResult(
                    user_id=user_id, status="skipped", reason=str(error)
                )
            )
            continue
        except Exception as error:  # noqa: BLE001 - 다음 사용자 처리를 계속한다
            logger.warning(
                "관심사 주기 재계산 실패 (user=%s)", user_id, exc_info=True
            )
            results.append(
                InterestRecalculationResult(
                    user_id=user_id, status="failed", reason=str(error)
                )
            )
            continue

        interests = profile.get("interests") or []
        # 수집 대상 갱신 실패가 이미 저장된 Profile을 실패로 뒤집으면 안 된다.
        try:
            subscribed = await sync_wiki_interest_collection_targets(
                connection, user_id=user_id, interests=interests
            )
        except Exception:  # noqa: BLE001 - Profile 재계산 성과는 유지한다
            logger.warning(
                "관심사 수집 대상 갱신 실패 — Profile은 유지 (user=%s)",
                user_id,
                exc_info=True,
            )
            subscribed = []
        version = profile.get("version")
        results.append(
            InterestRecalculationResult(
                user_id=user_id,
                status="completed",
                version=version if isinstance(version, int) else None,
                interest_count=len(interests),
                subscribed_targets=tuple(subscribed),
            )
        )
    return results


@dataclass(frozen=True, slots=True)
class MaintenanceRebuildResult:
    """정기 유지보수 재구성 Job 등록 결과 한 건."""

    user_id: str
    status: Literal["enqueued", "existing", "failed"]
    job_id: str | None = None
    reason: str | None = None


def _maintenance_key(moment: datetime) -> str:
    """같은 날 중복 등록을 막는 주기 식별자를 만든다."""
    return moment.astimezone(UTC).strftime("%Y-%m-%d")


async def schedule_personal_wiki_maintenance_rebuilds(
    connection: AsyncConnection[dict[str, Any]],
    *,
    stale_after_hours: float = 168.0,
    limit: int = 5,
    now: datetime | None = None,
) -> list[MaintenanceRebuildResult]:
    """정기 Wiki 재구성이 밀린 사용자에게 Full Rebuild Job을 등록한다.

    증분 Build는 원본이 들어올 때만 돌아 누적된 중복·고아 문서를 정리할
    기회가 없다. 이 단계는 그 정리를 시계로 돌린다. 실제 재구성은 등록된
    Job을 상주 Worker(WORKER-002)가 집어 수행하므로 여기서는 LLM을 부르지
    않는다.

    사용자 한 명의 등록 실패가 나머지를 막지 않도록 사용자 단위로 격리한다.

    Args:
        connection: 이미 열린 agent-db 커넥션
        stale_after_hours: 마지막 정기 재구성으로부터 기다릴 시간
        limit: 한 번의 실행에서 등록할 최대 Job 수
        now: 판정 기준 시각 (미지정 시 현재 UTC)

    Returns:
        사용자별 등록 결과 목록 (대상이 없으면 빈 목록)
    """
    users = await list_users_for_maintenance_rebuild(
        connection,
        stale_after_hours=stale_after_hours,
        limit=limit,
        now=now,
    )
    key = _maintenance_key(now or datetime.now(UTC))
    results: list[MaintenanceRebuildResult] = []
    for user_id in users:
        try:
            enqueued = await enqueue_personal_wiki_maintenance_rebuild_job(
                connection, user_id=user_id, maintenance_key=key
            )
        except Exception as error:  # noqa: BLE001 - 다음 사용자 등록을 계속한다
            logger.warning(
                "정기 Wiki 재구성 등록 실패 (user=%s)", user_id, exc_info=True
            )
            results.append(
                MaintenanceRebuildResult(
                    user_id=user_id, status="failed", reason=str(error)
                )
            )
            continue
        results.append(
            MaintenanceRebuildResult(
                user_id=user_id,
                status="enqueued" if enqueued.created else "existing",
                job_id=enqueued.job_id,
            )
        )
    return results
