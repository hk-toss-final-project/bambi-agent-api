"""기능 구현 모듈.

PLAN-011, PLAN-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def plan_011(request: FeatureRequest) -> FeatureResult:
    """[PLAN-011] 플랜별 생성 빈도.

    정기 생성과 요청 가능 횟수를 차등화한다.
    """
    raise NotImplementedError("[PLAN-011] 기능 구현이 필요합니다.")


async def plan_012(request: FeatureRequest) -> FeatureResult:
    """[PLAN-012] 플랜별 사용량 제한.

    Agent 기능별 사용 가능량을 제한한다.
    """
    raise NotImplementedError("[PLAN-012] 기능 구현이 필요합니다.")
