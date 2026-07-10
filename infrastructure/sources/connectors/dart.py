"""기능 구현 모듈.

COL-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def col_007(request: FeatureRequest) -> FeatureResult:
    """[COL-007] DART 수집.

    기업 공시 데이터를 수집한다.
    """
    raise NotImplementedError("[COL-007] 기능 구현이 필요합니다.")
