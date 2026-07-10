"""기능 구현 모듈.

WORKER-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def worker_012(request: FeatureRequest) -> FeatureResult:
    """[WORKER-012] Event Publisher Worker.

    Outbox 이벤트를 Integration Event Bus로 발행한다.
    """
    raise NotImplementedError("[WORKER-012] 기능 구현이 필요합니다.")
