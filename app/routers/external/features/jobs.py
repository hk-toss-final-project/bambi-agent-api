"""기능 구현 모듈.

EXT-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ext_008(request: FeatureRequest) -> FeatureResult:
    """[EXT-008] 외부 Job 상태 조회.

    비동기 작업 상태와 결과를 조회한다.
    """
    raise NotImplementedError("[EXT-008] 기능 구현이 필요합니다.")
