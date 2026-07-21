"""기능 구현 모듈.

INT-002 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def int_002(request: FeatureRequest) -> FeatureResult:
    """[INT-002] 관심사 Category 분류.

    관심사를 서비스의 분류 체계에 매핑한다.
    """
    return await execute_feature_implementation(request, feature_id="INT-002")
