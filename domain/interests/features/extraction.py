"""기능 구현 모듈.

INT-001 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def int_001(request: FeatureRequest) -> FeatureResult:
    """[INT-001] 관심사 Topic 추출.

    개인 Wiki와 사용자 행동에서 관심 주제를 추출한다.
    """
    return await execute_feature_implementation(request, feature_id="INT-001")
