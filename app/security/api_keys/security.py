"""기능 구현 모듈.

KEY-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def key_008(request: FeatureRequest) -> FeatureResult:
    """[KEY-008] API Key Hash 저장.

    원본 Key 대신 안전한 Hash를 저장한다.
    """
    raise NotImplementedError("[KEY-008] 기능 구현이 필요합니다.")
