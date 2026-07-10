"""기능 구현 모듈.

PLAN-009 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def plan_009(request: FeatureRequest) -> FeatureResult:
    """[PLAN-009] 플랜별 이미지 생성.

    플랜에 따라 이미지 기능을 제공하거나 제한한다.
    """
    raise NotImplementedError("[PLAN-009] 기능 구현이 필요합니다.")
