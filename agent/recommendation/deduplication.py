"""기능 구현 모듈.

REC-013 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def rec_013(request: FeatureRequest) -> FeatureResult:
    """[REC-013] 중복 추천 제거.

    이미 본 콘텐츠와 유사한 추천을 제거한다.
    """
    raise NotImplementedError("[REC-013] 기능 구현이 필요합니다.")
