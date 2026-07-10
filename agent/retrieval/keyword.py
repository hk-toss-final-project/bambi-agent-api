"""기능 구현 모듈.

RET-001 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ret_001(request: FeatureRequest) -> FeatureResult:
    """[RET-001] Keyword Search 설정.

    키워드 검색 방식과 가중치를 설정한다.
    """
    raise NotImplementedError("[RET-001] 기능 구현이 필요합니다.")
