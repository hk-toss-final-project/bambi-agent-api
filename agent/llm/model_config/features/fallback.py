"""기능 구현 모듈.

MODEL-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def model_008(request: FeatureRequest) -> FeatureResult:
    """[MODEL-008] 모델 Fallback 정책.

    모델 장애 시 대체 모델 순서를 관리한다.
    """
    raise NotImplementedError("[MODEL-008] 기능 구현이 필요합니다.")
