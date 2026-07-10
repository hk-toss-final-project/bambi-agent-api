"""기능 구현 모듈.

COL-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def col_006(request: FeatureRequest) -> FeatureResult:
    """[COL-006] 블로그 수집.

    블로그와 공개 게시글 데이터를 수집한다.
    """
    raise NotImplementedError("[COL-006] 기능 구현이 필요합니다.")
