"""기능 구현 모듈.

COL-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def col_012(request: FeatureRequest) -> FeatureResult:
    """[COL-012] 사용자 정의 Source 수집.

    추가된 외부 API와 Source Connector를 실행한다.
    """
    raise NotImplementedError("[COL-012] 기능 구현이 필요합니다.")
