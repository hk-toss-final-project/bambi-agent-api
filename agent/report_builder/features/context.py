"""기능 구현 모듈.

REPORT-003, REPORT-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


async def report_003(request: FeatureRequest) -> FeatureResult:
    """[REPORT-003] 사용자 컨텍스트 조회.

    생성에 필요한 사용자 설정과 플랜을 조회한다.
    """
    raise NotImplementedError("[REPORT-003] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def report_012(request: FeatureRequest) -> FeatureResult:
    """[REPORT-012] 사용자 개인화 적용.

    관심사, 언어, 비선호 설정을 반영한다.
    """
    return await execute_feature_implementation(request, feature_id="REPORT-012")
