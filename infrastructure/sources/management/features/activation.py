"""기능 구현 모듈.

GS-005, GS-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def gs_005(request: FeatureRequest) -> FeatureResult:
    """[GS-005] Global Source 활성화.

    Source 수집을 활성화한다.
    """
    raise NotImplementedError("[GS-005] 기능 구현이 필요합니다.")


async def gs_006(request: FeatureRequest) -> FeatureResult:
    """[GS-006] Global Source 비활성화.

    Source 수집을 일시 중지한다.
    """
    raise NotImplementedError("[GS-006] 기능 구현이 필요합니다.")
