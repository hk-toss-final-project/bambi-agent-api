"""기능 구현 모듈.

WORKER-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def worker_005(request: FeatureRequest) -> FeatureResult:
    """[WORKER-005] Summary Worker.

    요약 작업을 수행한다.
    """
    raise NotImplementedError("[WORKER-005] 기능 구현이 필요합니다.")
