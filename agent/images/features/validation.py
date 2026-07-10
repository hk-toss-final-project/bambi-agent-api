"""기능 구현 모듈.

IMG-008, IMG-009, IMG-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def img_008(request: FeatureRequest) -> FeatureResult:
    """[IMG-008] 이미지 안전성 검사.

    생성 이미지의 정책 위반 여부를 검사한다.
    """
    raise NotImplementedError("[IMG-008] 기능 구현이 필요합니다.")


async def img_009(request: FeatureRequest) -> FeatureResult:
    """[IMG-009] 이미지 품질 평가.

    관련성, 해상도, 텍스트 오류를 평가한다.
    """
    raise NotImplementedError("[IMG-009] 기능 구현이 필요합니다.")


async def img_010(request: FeatureRequest) -> FeatureResult:
    """[IMG-010] 이미지 재생성.

    품질 기준을 충족하지 못한 이미지를 다시 생성한다.
    """
    raise NotImplementedError("[IMG-010] 기능 구현이 필요합니다.")
