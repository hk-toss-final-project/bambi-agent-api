"""기능 구현 모듈.

WORKER-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def worker_010(request: FeatureRequest) -> FeatureResult:
    """[WORKER-010] Reindex Worker.

    Embedding 모델 변경 시 재색인한다.
    """
    raise NotImplementedError("[WORKER-010] 기능 구현이 필요합니다.")
