"""기능 구현 모듈.

MODEL-002 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def model_002(request: FeatureRequest) -> FeatureResult:
    """[MODEL-002] Model Config 조회.

    작업별 모델 설정을 조회한다.
    """
    raise NotImplementedError("[MODEL-002] 기능 구현이 필요합니다.")
