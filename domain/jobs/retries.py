"""기능 구현 모듈.

JOB-005, JOB-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def job_005(request: FeatureRequest) -> FeatureResult:
    """[JOB-005] Agent Job 재시도.

    실패한 작업을 다시 실행한다.
    """
    raise NotImplementedError("[JOB-005] 기능 구현이 필요합니다.")


async def job_012(request: FeatureRequest) -> FeatureResult:
    """[JOB-012] Agent Job Dead Letter.

    반복 실패 작업을 별도 Queue로 격리한다.
    """
    raise NotImplementedError("[JOB-012] 기능 구현이 필요합니다.")
