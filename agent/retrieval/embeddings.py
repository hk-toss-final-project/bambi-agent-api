"""기능 구현 모듈.

RET-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ret_007(request: FeatureRequest) -> FeatureResult:
    """[RET-007] Embedding 설정.

    Embedding 모델과 버전을 설정한다.
    """
    raise NotImplementedError("[RET-007] 기능 구현이 필요합니다.")
