"""기능 구현 모듈.

COL-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def col_005(request: FeatureRequest) -> FeatureResult:
    """[COL-005] SNS 수집.

    허용된 SNS 공개 데이터를 수집한다.
    """
    raise NotImplementedError("[COL-005] 기능 구현이 필요합니다.")
