"""기능 구현 모듈.

WORKER-009 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def worker_009(request: FeatureRequest) -> FeatureResult:
    """[WORKER-009] Embedding Worker.

    문서와 Chunk의 Embedding을 생성한다.
    """
    raise NotImplementedError("[WORKER-009] 기능 구현이 필요합니다.")
