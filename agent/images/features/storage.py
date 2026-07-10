"""기능 구현 모듈.

IMG-011, IMG-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def img_011(request: FeatureRequest) -> FeatureResult:
    """[IMG-011] 이미지 저장.

    생성된 이미지를 Object Storage에 저장한다.
    """
    raise NotImplementedError("[IMG-011] 기능 구현이 필요합니다.")


async def img_012(request: FeatureRequest) -> FeatureResult:
    """[IMG-012] 콘텐츠 이미지 연결.

    이미지 Asset을 생성 콘텐츠와 연결한다.
    """
    raise NotImplementedError("[IMG-012] 기능 구현이 필요합니다.")
