"""기능 구현 모듈.

ADMIN-012, ADMIN-013 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def admin_012(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-012] Agent Job 조회.

    전체 Agent 작업 상태를 조회한다.
    """
    raise NotImplementedError("[ADMIN-012] 기능 구현이 필요합니다.")


async def admin_013(request: FeatureRequest) -> FeatureResult:
    """[ADMIN-013] Agent Job 재시도.

    실패한 Agent 작업을 다시 실행한다.
    """
    raise NotImplementedError("[ADMIN-013] 기능 구현이 필요합니다.")
