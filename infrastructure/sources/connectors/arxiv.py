"""기능 구현 모듈.

COL-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def col_010(request: FeatureRequest) -> FeatureResult:
    """[COL-010] arXiv 수집.

    논문 메타데이터, 초록, 본문을 수집한다.
    """
    raise NotImplementedError("[COL-010] 기능 구현이 필요합니다.")
