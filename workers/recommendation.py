"""기능 구현 모듈.

WORKER-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def worker_008(request: FeatureRequest) -> FeatureResult:
    """[WORKER-008] Recommendation Worker.

    사용자별 추천 후보를 생성한다.
    """
    raise NotImplementedError("[WORKER-008] 기능 구현이 필요합니다.")
