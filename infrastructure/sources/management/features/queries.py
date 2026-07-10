"""기능 구현 모듈.

GS-002 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def gs_002(request: FeatureRequest) -> FeatureResult:
    """[GS-002] Global Source 조회.

    등록된 Source와 설정을 조회한다.
    """
    raise NotImplementedError("[GS-002] 기능 구현이 필요합니다.")
