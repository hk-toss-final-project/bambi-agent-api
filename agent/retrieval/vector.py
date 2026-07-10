"""기능 구현 모듈.

RET-002 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ret_002(request: FeatureRequest) -> FeatureResult:
    """[RET-002] Vector Search 설정.

    Vector 검색 방식과 Threshold를 설정한다.
    """
    raise NotImplementedError("[RET-002] 기능 구현이 필요합니다.")
