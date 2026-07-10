"""기능 구현 모듈.

PLAN-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def plan_005(request: FeatureRequest) -> FeatureResult:
    """[PLAN-005] 플랜별 Retrieval 범위.

    개인 Wiki와 Global Source 검색 깊이를 차등화한다.
    """
    raise NotImplementedError("[PLAN-005] 기능 구현이 필요합니다.")
