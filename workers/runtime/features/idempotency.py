"""기능 구현 모듈.

WC-009, WC-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wc_009(request: FeatureRequest) -> FeatureResult:
    """[WC-009] Idempotency 처리.

    중복 작업 실행에도 동일 결과를 보장한다.
    """
    return await execute_feature_implementation(request, feature_id="WC-009")


async def wc_010(request: FeatureRequest) -> FeatureResult:
    """[WC-010] 작업 중복 방지.

    동일 Resource에 대한 동시 작업을 방지한다.
    """
    raise NotImplementedError("[WC-010] 기능 구현이 필요합니다.")
