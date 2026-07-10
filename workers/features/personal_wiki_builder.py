"""기능 구현 모듈.

WORKER-002 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def worker_002(request: FeatureRequest) -> FeatureResult:
    """[WORKER-002] Personal Wiki Builder Worker.

    사용자 선택 데이터를 개인 Wiki로 구성한다.
    """
    raise NotImplementedError("[WORKER-002] 기능 구현이 필요합니다.")
