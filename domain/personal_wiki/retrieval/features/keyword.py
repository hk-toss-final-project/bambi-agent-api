"""기능 구현 모듈.

PRAG-001 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def prag_001(request: FeatureRequest) -> FeatureResult:
    """[PRAG-001] Keyword Search.

    개인 Wiki에서 키워드 기반 검색을 수행한다.
    """
    raise NotImplementedError("[PRAG-001] 기능 구현이 필요합니다.")
