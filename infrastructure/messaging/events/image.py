"""기능 구현 모듈.

EVT-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def evt_007(request: FeatureRequest) -> FeatureResult:
    """[EVT-007] Image Asset Ready 이벤트.

    이미지 Asset 생성 완료를 전달한다.
    """
    raise NotImplementedError("[EVT-007] 기능 구현이 필요합니다.")
