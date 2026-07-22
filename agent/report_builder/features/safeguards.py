"""기능 구현 모듈.

REPORT-021 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def report_021(request: FeatureRequest) -> FeatureResult:
    """[REPORT-021] 자동 Wiki 편입 금지.

    생성된 콘텐츠를 사용자 선택 없이 개인 Wiki에 넣지 않는다.
    """
    return await execute_feature_implementation(request, feature_id="REPORT-021")
