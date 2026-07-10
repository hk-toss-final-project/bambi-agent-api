"""기능 구현 모듈.

REC-018 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def rec_018(request: FeatureRequest) -> FeatureResult:
    """[REC-018] 추천 A/B Test.

    추천 알고리즘과 정책을 비교한다.
    """
    raise NotImplementedError("[REC-018] 기능 구현이 필요합니다.")
