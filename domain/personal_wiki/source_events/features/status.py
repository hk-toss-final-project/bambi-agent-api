"""개인 Wiki Source Event 상태 전이 검증 기능 구현."""

from typing import Literal

type SourceEventStatus = Literal["received", "processing", "completed", "failed", "ignored"]


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wse_013(status: str) -> SourceEventStatus:
    """[WSE-013] 이벤트 처리 상태 관리.

    수신, 처리 중, 완료, 실패 상태를 관리한다.
    """
    allowed: set[str] = {"received", "processing", "completed", "failed", "ignored"}
    if status not in allowed:
        raise ValueError(f"WSE-013이 허용하지 않는 Source Event 상태입니다: {status}")
    return status  # type: ignore[return-value]
