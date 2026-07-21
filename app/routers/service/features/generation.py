"""기능 구현 모듈.

SVC-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_008(request: FeatureRequest) -> FeatureResult:
    """[SVC-008] 콘텐츠 생성 요청.

    밤비의 콘텐츠 생성을 요청한다.
    """
    return await execute_feature_implementation(request, feature_id="SVC-008")
