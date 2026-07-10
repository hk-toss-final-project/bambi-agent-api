"""기능 구현 모듈.

REC-014 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def rec_014(request: FeatureRequest) -> FeatureResult:
    """[REC-014] 비선호 반영.

    숨김, 차단, 신고 정보를 추천에서 반영한다.
    """
    raise NotImplementedError("[REC-014] 기능 구현이 필요합니다.")
