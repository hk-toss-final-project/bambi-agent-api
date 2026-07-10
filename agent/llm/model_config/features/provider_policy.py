"""기능 구현 모듈.

MODEL-007, MODEL-010, MODEL-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def model_007(request: FeatureRequest) -> FeatureResult:
    """[MODEL-007] Provider별 모델 정책.

    Provider별 우선순위와 사용 조건을 설정한다.
    """
    raise NotImplementedError("[MODEL-007] 기능 구현이 필요합니다.")


async def model_010(request: FeatureRequest) -> FeatureResult:
    """[MODEL-010] Provider 활성화.

    특정 Provider의 사용을 활성화한다.
    """
    raise NotImplementedError("[MODEL-010] 기능 구현이 필요합니다.")


async def model_011(request: FeatureRequest) -> FeatureResult:
    """[MODEL-011] Provider 비활성화.

    장애나 정책에 따라 Provider 사용을 중단한다.
    """
    raise NotImplementedError("[MODEL-011] 기능 구현이 필요합니다.")
