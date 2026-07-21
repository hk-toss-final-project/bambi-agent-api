"""기능 구현 모듈.

BAMBI-004, BAMBI-005, BAMBI-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def bambi_004(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-004] 개인 Wiki 검색.

    사용자의 관심사와 기존 지식을 검색한다.
    """
    return await execute_feature_implementation(request, feature_id="BAMBI-004")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def bambi_005(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-005] Global Source 검색.

    최신 외부 자료와 근거를 검색한다.
    """
    return await execute_feature_implementation(request, feature_id="BAMBI-005")


async def bambi_006(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-006] 생성 자료 선별.

    콘텐츠 생성에 사용할 자료를 선별한다.
    """
    raise NotImplementedError("[BAMBI-006] 기능 구현이 필요합니다.")
