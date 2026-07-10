"""기능 구현 모듈.

IMG-017 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def img_017(request: FeatureRequest) -> FeatureResult:
    """[IMG-017] 플랜별 이미지 제한.

    플랜별 생성 횟수와 기능 범위를 제한한다.
    """
    raise NotImplementedError("[IMG-017] 기능 구현이 필요합니다.")
