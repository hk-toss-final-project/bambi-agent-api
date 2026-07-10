"""기능 구현 모듈.

IMG-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def img_007(request: FeatureRequest) -> FeatureResult:
    """[IMG-007] 이미지 Prompt 생성.

    콘텐츠를 이미지 생성 Prompt로 변환한다.
    """
    raise NotImplementedError("[IMG-007] 기능 구현이 필요합니다.")
