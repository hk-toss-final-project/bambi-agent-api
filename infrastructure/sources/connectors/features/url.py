"""기능 구현 모듈.

COL-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def col_011(request: FeatureRequest) -> FeatureResult:
    """[COL-011] 직접 URL 수집.

    관리자가 지정한 URL의 데이터를 수집한다.
    """
    raise NotImplementedError("[COL-011] 기능 구현이 필요합니다.")
