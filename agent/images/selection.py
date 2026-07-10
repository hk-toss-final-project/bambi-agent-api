"""기능 구현 모듈.

IMG-013 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def img_013(request: FeatureRequest) -> FeatureResult:
    """[IMG-013] 대표 이미지 선택.

    여러 Asset 중 대표 이미지를 선택한다.
    """
    raise NotImplementedError("[IMG-013] 기능 구현이 필요합니다.")
