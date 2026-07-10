"""기능 구현 모듈.

REC-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def rec_010(request: FeatureRequest) -> FeatureResult:
    """[REC-010] 추천 이유 생성.

    추천된 이유를 사용자에게 설명한다.
    """
    raise NotImplementedError("[REC-010] 기능 구현이 필요합니다.")
