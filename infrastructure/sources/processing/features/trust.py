"""기능 구현 모듈.

GSP-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def gsp_012(request: FeatureRequest) -> FeatureResult:
    """[GSP-012] Source 신뢰도 관리.

    Source별 품질과 신뢰도 정보를 관리한다.
    """
    raise NotImplementedError("[GSP-012] 기능 구현이 필요합니다.")
