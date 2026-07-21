"""기능 구현 모듈.

COL-002 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def col_002(request: FeatureRequest) -> FeatureResult:
    """[COL-002] Naver API 수집.

    설정된 키워드로 Naver API 데이터를 수집한다.
    """
    return await execute_feature_implementation(request, feature_id="COL-002")
