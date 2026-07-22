"""Agent Job 진행률 전이 검증 기능 구현."""


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def job_006(current: int, target: int) -> int:
    """[JOB-006] Agent Job 진행률 관리.

    긴 작업의 단계와 진행률을 기록한다.
    """
    if not 0 <= current <= 100 or not 0 <= target <= 100:
        raise ValueError("JOB-006 진행률은 0에서 100 사이여야 합니다.")
    if target < current:
        raise ValueError("JOB-006 진행률은 이전 값보다 작아질 수 없습니다.")
    return target
