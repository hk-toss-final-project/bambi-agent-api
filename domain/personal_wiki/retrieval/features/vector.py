"""기능 구현 모듈.

PRAG-002 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def prag_002(request: FeatureRequest) -> FeatureResult:
    """[PRAG-002] Vector Search.

    개인 Wiki에서 의미 유사도 검색을 수행한다.
    """
    raise NotImplementedError("[PRAG-002] 기능 구현이 필요합니다.")
