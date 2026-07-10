"""기능 구현 모듈.

IMG-014 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def img_014(request: FeatureRequest) -> FeatureResult:
    """[IMG-014] 이미지 Alt Text 생성.

    접근성을 위한 이미지 설명을 생성한다.
    """
    raise NotImplementedError("[IMG-014] 기능 구현이 필요합니다.")
