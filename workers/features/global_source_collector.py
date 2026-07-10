"""기능 구현 모듈.

WORKER-001 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def worker_001(request: FeatureRequest) -> FeatureResult:
    """[WORKER-001] Global Source Collector Worker.

    외부 데이터를 수집하고 Global Source Pool에 저장한다.
    """
    raise NotImplementedError("[WORKER-001] 기능 구현이 필요합니다.")
