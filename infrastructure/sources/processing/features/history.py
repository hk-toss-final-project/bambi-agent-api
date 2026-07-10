"""기능 구현 모듈.

GSP-013 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def gsp_013(request: FeatureRequest) -> FeatureResult:
    """[GSP-013] 수집 이력 관리.

    수집 실행 결과와 신규·중복·실패 건수를 기록한다.
    """
    raise NotImplementedError("[GSP-013] 기능 구현이 필요합니다.")
