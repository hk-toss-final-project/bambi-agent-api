"""기능 구현 모듈.

INT-005, INT-006, INT-008, INT-009 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def int_005(request: FeatureRequest) -> FeatureResult:
    """[INT-005] 관심사 점수 계산.

    사용자 행동 강도와 최신성을 기반으로 점수를 계산한다.
    """
    return await execute_feature_implementation(request, feature_id="INT-005")


async def int_006(request: FeatureRequest) -> FeatureResult:
    """[INT-006] 관심사 Confidence 계산.

    추론된 관심사의 신뢰도를 계산한다.
    """
    raise NotImplementedError("[INT-006] 기능 구현이 필요합니다.")


async def int_008(request: FeatureRequest) -> FeatureResult:
    """[INT-008] 관심사 시간 감쇠.

    오래된 관심사의 가중치를 점진적으로 낮춘다.
    """
    raise NotImplementedError("[INT-008] 기능 구현이 필요합니다.")


async def int_009(request: FeatureRequest) -> FeatureResult:
    """[INT-009] 비선호 관심사 반영.

    숨김, 차단, 신고 등의 부정 신호를 반영한다.
    """
    raise NotImplementedError("[INT-009] 기능 구현이 필요합니다.")
