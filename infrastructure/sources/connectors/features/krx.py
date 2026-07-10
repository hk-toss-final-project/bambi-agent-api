"""기능 구현 모듈.

COL-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def col_008(request: FeatureRequest) -> FeatureResult:
    """[COL-008] KRX 수집.

    시장 및 종목 관련 데이터를 수집한다.
    """
    raise NotImplementedError("[COL-008] 기능 구현이 필요합니다.")
