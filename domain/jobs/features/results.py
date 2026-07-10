"""기능 구현 모듈.

JOB-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def job_007(request: FeatureRequest) -> FeatureResult:
    """[JOB-007] Agent Job 결과 연결.

    완료된 작업과 결과 데이터를 연결한다.
    """
    raise NotImplementedError("[JOB-007] 기능 구현이 필요합니다.")
