"""기능 구현 모듈.

BAMBI-018, BAMBI-019 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def bambi_018(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-018] 생성 콘텐츠 후보 저장.

    발행 전 콘텐츠를 agent-db에 저장한다.
    """
    return await execute_feature_implementation(request, feature_id="BAMBI-018")


async def bambi_019(request: FeatureRequest) -> FeatureResult:
    """[BAMBI-019] 발행 가능 상태 전환.

    품질 기준을 통과한 콘텐츠를 발행 가능 상태로 변경한다.
    """
    raise NotImplementedError("[BAMBI-019] 기능 구현이 필요합니다.")
