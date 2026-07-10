"""기능 구현 모듈.

COL-003 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def col_003(request: FeatureRequest) -> FeatureResult:
    """[COL-003] GDELT 수집.

    글로벌 뉴스와 이벤트 데이터를 수집한다.
    """
    raise NotImplementedError("[COL-003] 기능 구현이 필요합니다.")
