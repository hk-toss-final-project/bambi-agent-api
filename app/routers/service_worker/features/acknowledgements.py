"""기능 구현 모듈.

SW-009, SW-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def sw_009(request: FeatureRequest) -> FeatureResult:
    """[SW-009] 발행 완료 ACK.

    service-db 반영 완료를 Agent API에 알린다.
    """
    return await execute_feature_implementation(request, feature_id="SW-009")


async def sw_010(request: FeatureRequest) -> FeatureResult:
    """[SW-010] 발행 실패 전달.

    발행 실패 사유를 Agent API에 전달한다.
    """
    raise NotImplementedError("[SW-010] 기능 구현이 필요합니다.")
