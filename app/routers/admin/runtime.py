"""기능 구현 모듈.

ADMIN-018, ADMIN-019 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def admin_018(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-018] Worker 상태 조회.

    Worker의 상태와 처리량을 조회한다.
    """
    raise NotImplementedError("[ADMIN-018] 기능 구현이 필요합니다.")


async def admin_019(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-019] Queue 상태 조회.

    Queue 적체와 실패 작업을 조회한다.
    """
    raise NotImplementedError("[ADMIN-019] 기능 구현이 필요합니다.")
