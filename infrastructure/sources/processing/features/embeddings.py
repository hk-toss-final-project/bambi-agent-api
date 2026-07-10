"""기능 구현 모듈.

GSP-010, GSP-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def gsp_010(request: FeatureRequest) -> FeatureResult:
    """[GSP-010] Global 문서 Embedding.

    Global Source 검색용 Vector를 생성한다.
    """
    raise NotImplementedError("[GSP-010] 기능 구현이 필요합니다.")


async def gsp_011(request: FeatureRequest) -> FeatureResult:
    """[GSP-011] Global Vector Index 관리.

    Global Source 전용 Vector Index를 관리한다.
    """
    raise NotImplementedError("[GSP-011] 기능 구현이 필요합니다.")
