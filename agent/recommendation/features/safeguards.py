"""기능 구현 모듈.

REC-019 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def rec_019(request: FeatureRequest) -> FeatureResult:
    """[REC-019] 자동 Wiki 편입 금지.

    추천만으로 개인 Wiki에 콘텐츠를 추가하지 않는다.
    """
    raise NotImplementedError("[REC-019] 기능 구현이 필요합니다.")
