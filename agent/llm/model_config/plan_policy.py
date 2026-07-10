"""기능 구현 모듈.

MODEL-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def model_006(request: FeatureRequest) -> FeatureResult:
    """[MODEL-006] 플랜별 모델 정책.

    무료와 유료 플랜의 모델 사용 정책을 설정한다.
    """
    raise NotImplementedError("[MODEL-006] 기능 구현이 필요합니다.")
