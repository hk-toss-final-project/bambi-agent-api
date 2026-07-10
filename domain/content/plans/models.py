"""기능 구현 모듈.

PLAN-003 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def plan_003(request: FeatureRequest) -> FeatureResult:
    """[PLAN-003] 플랜별 모델 선택.

    플랜에 따라 사용할 LLM 모델을 선택한다.
    """
    raise NotImplementedError("[PLAN-003] 기능 구현이 필요합니다.")
