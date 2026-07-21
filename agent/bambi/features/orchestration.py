"""기능 구현 모듈.

BAMBI-001, BAMBI-002 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def bambi_001(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-001] 콘텐츠 생성 요청.

    사용자와 주제에 맞는 콘텐츠 생성 요청을 처리한다.
    """
    return await execute_feature_implementation(request, feature_id="BAMBI-001")


async def bambi_002(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-002] 콘텐츠 생성 계획.

    검색 범위, 콘텐츠 구조, 모델을 결정한다.
    """
    raise NotImplementedError("[BAMBI-002] 기능 구현이 필요합니다.")
