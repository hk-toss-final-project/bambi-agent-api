"""기능 구현 모듈.

JOB-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult
from shared.feature_runtime import execute_feature_implementation


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def job_006(request: FeatureRequest) -> FeatureResult:
    """[JOB-006] Agent Job 진행률 관리.

    긴 작업의 단계와 진행률을 기록한다.
    """
    return await execute_feature_implementation(request, feature_id="JOB-006")
