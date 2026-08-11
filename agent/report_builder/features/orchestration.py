"""기능 구현 모듈.

REPORT-001, REPORT-002, REPORT-022 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def report_001(request: FeatureRequest) -> FeatureResult:
    """[REPORT-001] 콘텐츠 생성 요청.

    사용자와 주제에 맞는 콘텐츠 생성 요청을 처리한다.
    """
    return await execute_feature_implementation(request, feature_id="REPORT-001")


async def report_002(request: FeatureRequest) -> FeatureResult:
    """[REPORT-002] 콘텐츠 생성 계획.

    검색 범위, 콘텐츠 구조, 모델을 결정한다.
    """
    raise NotImplementedError("[REPORT-002] 기능 구현이 필요합니다.")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def report_022(request: FeatureRequest) -> FeatureResult:
    """[REPORT-022] 아침 브리핑 사전 준비.

    날짜별 주제를 선정하고 Wiki·Global·Live 근거를 생성 전에 Snapshot으로 준비한다.
    """
    return await execute_feature_implementation(request, feature_id="REPORT-022")
