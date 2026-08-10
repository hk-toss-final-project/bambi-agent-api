"""기능 구현 모듈.

SCH-009, SCH-010 기능의 실제 구현 위치를 제공한다.

SCH-009는 수집으로 누적된 personal_wiki_build Job의 실행 시각을
조용 시간(quiet window)과 최대 대기시간 정책으로 조정한다.

SCH-010은 관심사 Profile이 오래된 사용자를 주기적으로 다시 계산한다.
관심사 점수는 계산 시각 기준으로 최신성을 감쇠시키므로, 저장이 멈춘 사용자는
재계산이 돌지 않으면 마지막 Build 시점 점수에 그대로 고정된다.
"""

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Literal

from psycopg import AsyncConnection

from domain.interests.api import ActiveWikiRequiredError, int_011
from infrastructure.persistence.api import (
    ConnectionInterestProfileRepository,
    defer_user_wiki_build_jobs,
    list_users_for_interest_recalculation,
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
