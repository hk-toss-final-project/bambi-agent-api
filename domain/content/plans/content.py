"""기능 구현 모듈.

PLAN-006, PLAN-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def plan_006(request: FeatureRequest) -> FeatureResult:
    """[PLAN-006] 플랜별 콘텐츠 길이.

    무료와 유료 콘텐츠의 길이를 다르게 설정한다.
    """
    raise NotImplementedError("[PLAN-006] 기능 구현이 필요합니다.")


async def plan_007(request: FeatureRequest) -> FeatureResult:
    """[PLAN-007] 플랜별 콘텐츠 상세도.

    배경 설명, 비교, 시사점의 깊이를 조정한다.
    """
    raise NotImplementedError("[PLAN-007] 기능 구현이 필요합니다.")
