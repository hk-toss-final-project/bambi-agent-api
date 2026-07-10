"""기능 구현 모듈.

MODEL-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def model_005(request: FeatureRequest) -> FeatureResult:
    """[MODEL-005] 작업별 모델 정책.

    요약, 번역, 생성 등 작업별 모델을 설정한다.
    """
    raise NotImplementedError("[MODEL-005] 기능 구현이 필요합니다.")
