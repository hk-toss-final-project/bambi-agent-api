"""기능 구현 모듈.

CTX-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ctx_005(request: FeatureRequest) -> FeatureResult:
    """[CTX-005] 컨텍스트 버전 관리.

    오래된 컨텍스트가 최신 데이터를 덮어쓰지 않도록 관리한다.
    """
    raise NotImplementedError("[CTX-005] 기능 구현이 필요합니다.")
