"""기능 구현 모듈.

GSP-001 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def gsp_001(request: FeatureRequest) -> FeatureResult:
    """[GSP-001] Raw 데이터 저장.

    외부 Source에서 받은 원본 데이터를 저장한다.
    """
    raise NotImplementedError("[GSP-001] 기능 구현이 필요합니다.")
