"""기능 구현 모듈.

WORKER-003 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def worker_003(request: FeatureRequest) -> FeatureResult:
    """[WORKER-003] Bambi Generation Worker.

    개인화 콘텐츠를 생성한다.
    """
    raise NotImplementedError("[WORKER-003] 기능 구현이 필요합니다.")
