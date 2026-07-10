"""기능 구현 모듈.

GSP-009 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def gsp_009(request: FeatureRequest) -> FeatureResult:
    """[GSP-009] Global 문서 Chunking.

    Global Source 문서를 검색 가능한 Chunk로 분할한다.
    """
    raise NotImplementedError("[GSP-009] 기능 구현이 필요합니다.")
