"""기능 구현 모듈.

SVC-013, SVC-014 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_013(request: FeatureRequest) -> FeatureResult:
    """[SVC-013] Agent Job 상태 조회.

    비동기 작업 상태를 조회한다.
    """
    return await execute_feature_implementation(request, feature_id="SVC-013")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_014(request: FeatureRequest) -> FeatureResult:
    """[SVC-014] Agent 결과 조회.

    생성 및 처리 결과를 Agent API에서 조회한다.
    """
    return await execute_feature_implementation(request, feature_id="SVC-014")
