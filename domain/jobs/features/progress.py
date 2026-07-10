"""기능 구현 모듈.

JOB-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def job_006(request: FeatureRequest) -> FeatureResult:
    """[JOB-006] Agent Job 진행률 관리.

    긴 작업의 단계와 진행률을 기록한다.
    """
    raise NotImplementedError("[JOB-006] 기능 구현이 필요합니다.")
