"""기능 구현 모듈.

PRAG-003 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def prag_003(request: FeatureRequest) -> FeatureResult:
    """[PRAG-003] Hybrid Search.

    Keyword와 Vector 검색 결과를 결합한다.
    """
    return await execute_feature_implementation(request, feature_id="PRAG-003")
