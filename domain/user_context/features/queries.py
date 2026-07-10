"""기능 구현 모듈.

CTX-003 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ctx_003(request: FeatureRequest) -> FeatureResult:
    """[CTX-003] 사용자 컨텍스트 조회.

    Agent 작업에서 사용할 사용자 컨텍스트를 조회한다.
    """
    raise NotImplementedError("[CTX-003] 기능 구현이 필요합니다.")
