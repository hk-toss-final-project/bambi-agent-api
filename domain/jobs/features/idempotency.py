"""Agent Job 멱등성 Key 생성 기능 구현."""

from collections.abc import Sequence


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def job_010(parts: Sequence[str]) -> str:
    """[JOB-010] Agent Job Idempotency.

    동일 요청으로 작업이 중복 실행되지 않도록 한다.
    """
    normalized = [part.strip() for part in parts]
    if not normalized or any(not part for part in normalized):
        raise ValueError("JOB-010 멱등성 Key 구성 값은 비어 있을 수 없습니다.")
    return ":".join(normalized)
