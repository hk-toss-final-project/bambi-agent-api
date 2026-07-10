"""기능 구현 모듈.

EVT-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def evt_006(request: FeatureRequest) -> FeatureResult:
    """[EVT-006] Recommendation Ready 이벤트.

    추천 후보가 준비되었음을 전달한다.
    """
    raise NotImplementedError("[EVT-006] 기능 구현이 필요합니다.")
