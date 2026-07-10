"""기능 구현 모듈.

COL-009 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def col_009(request: FeatureRequest) -> FeatureResult:
    """[COL-009] GitHub 수집.

    Repository, Release, Issue, README 등을 수집한다.
    """
    raise NotImplementedError("[COL-009] 기능 구현이 필요합니다.")
