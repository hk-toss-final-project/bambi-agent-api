"""기능 구현 모듈.

WORKER-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def worker_007(request: FeatureRequest) -> FeatureResult:
    """[WORKER-007] Media Worker.

    이미지와 시각 자료를 생성한다.
    """
    raise NotImplementedError("[WORKER-007] 기능 구현이 필요합니다.")
