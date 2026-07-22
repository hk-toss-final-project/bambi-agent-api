"""기능 구현 모듈.

SCH-009, SCH-010 기능의 실제 구현 위치를 제공한다.

SCH-009는 수집으로 누적된 personal_wiki_build Job의 실행 시각을
조용 시간(quiet window)과 최대 대기시간 정책으로 조정한다.
"""

from dataclasses import dataclass
from typing import Any, Literal

from psycopg import AsyncConnection

from infrastructure.persistence.api import (
    defer_user_wiki_build_jobs,
    release_user_wiki_build_jobs,
)
from shared.contracts import FeatureRequest, FeatureResult


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


async def sch_010(request: FeatureRequest) -> FeatureResult:
    """[SCH-010] 사용자 관심사 재계산.

    개인 Wiki 변경에 따라 관심사 프로필을 재계산한다.
    """
    raise NotImplementedError("[SCH-010] 기능 구현이 필요합니다.")
