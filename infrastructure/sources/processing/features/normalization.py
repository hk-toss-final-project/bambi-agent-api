"""기능 구현 모듈.

GSP-004, GSP-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def gsp_004(request: FeatureRequest) -> FeatureResult:
    """[GSP-004] API 응답 정규화.

    Source별 응답을 공통 문서 구조로 변환한다.
    """
    return await execute_feature_implementation(request, feature_id="GSP-004")


async def gsp_005(request: FeatureRequest) -> FeatureResult:
    """[GSP-005] 문서 언어 감지.

    수집된 문서의 언어를 판별한다.
    """
    raise NotImplementedError("[GSP-005] 기능 구현이 필요합니다.")
