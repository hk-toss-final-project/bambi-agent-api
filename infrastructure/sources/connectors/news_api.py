"""기능 구현 모듈.

COL-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def col_004(request: FeatureRequest) -> FeatureResult:
    """[COL-004] NewsAPI 수집.

    뉴스 기사와 관련 메타데이터를 수집한다.
    """
    raise NotImplementedError("[COL-004] 기능 구현이 필요합니다.")
