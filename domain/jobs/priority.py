"""기능 구현 모듈.

JOB-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def job_011(request: FeatureRequest) -> FeatureResult:
    """[JOB-011] Agent Job 우선순위.

    중요도에 따라 작업 처리 순서를 조정한다.
    """
    raise NotImplementedError("[JOB-011] 기능 구현이 필요합니다.")
