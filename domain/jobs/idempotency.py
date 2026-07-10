"""기능 구현 모듈.

JOB-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def job_010(request: FeatureRequest) -> FeatureResult:
    """[JOB-010] Agent Job Idempotency.

    동일 요청으로 작업이 중복 실행되지 않도록 한다.
    """
    raise NotImplementedError("[JOB-010] 기능 구현이 필요합니다.")
