"""기능 구현 모듈.

GSP-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def gsp_008(request: FeatureRequest) -> FeatureResult:
    """[GSP-008] 문서 버전 관리.

    외부 문서 변경 이력을 관리한다.
    """
    raise NotImplementedError("[GSP-008] 기능 구현이 필요합니다.")
