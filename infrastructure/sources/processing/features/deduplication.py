"""기능 구현 모듈.

GSP-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def gsp_006(request: FeatureRequest) -> FeatureResult:
    """[GSP-006] 문서 중복 제거.

    동일 URL과 유사 문서를 중복 제거한다.
    """
    return await execute_feature_implementation(request, feature_id="GSP-006")
