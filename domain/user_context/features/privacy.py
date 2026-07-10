"""기능 구현 모듈.

CTX-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ctx_011(request: FeatureRequest) -> FeatureResult:
    """[CTX-011] 개인정보 최소화.

    Agent에 불필요한 개인정보가 저장되지 않도록 제한한다.
    """
    raise NotImplementedError("[CTX-011] 기능 구현이 필요합니다.")
