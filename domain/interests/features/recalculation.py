"""기능 구현 모듈.

INT-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def int_011(request: FeatureRequest) -> FeatureResult:
    """[INT-011] 관심사 프로필 재계산.

    Wiki 변경 시 관심사 구조와 점수를 다시 계산한다.
    """
    return await execute_feature_implementation(request, feature_id="INT-011")
