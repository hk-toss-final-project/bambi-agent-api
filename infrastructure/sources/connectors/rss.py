"""기능 구현 모듈.

COL-001 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def col_001(request: FeatureRequest) -> FeatureResult:
    """[COL-001] RSS 수집.

    등록된 RSS Feed에서 신규 콘텐츠를 수집한다.
    """
    raise NotImplementedError("[COL-001] 기능 구현이 필요합니다.")
