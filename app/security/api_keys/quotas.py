"""기능 구현 모듈.

KEY-010, KEY-011, KEY-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def key_010(request: FeatureRequest) -> FeatureResult:
    """[KEY-010] API Key Quota 설정.

    기간별 호출량과 Token 한도를 설정한다.
    """
    raise NotImplementedError("[KEY-010] 기능 구현이 필요합니다.")


async def key_011(request: FeatureRequest) -> FeatureResult:
    """[KEY-011] API Key Rate Limit.

    초·분 단위 호출 제한을 적용한다.
    """
    raise NotImplementedError("[KEY-011] 기능 구현이 필요합니다.")


async def key_012(request: FeatureRequest) -> FeatureResult:
    """[KEY-012] API Key 사용량 조회.

    호출량, Token, 비용을 조회한다.
    """
    raise NotImplementedError("[KEY-012] 기능 구현이 필요합니다.")
