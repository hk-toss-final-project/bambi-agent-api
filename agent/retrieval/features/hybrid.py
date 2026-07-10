"""기능 구현 모듈.

RET-003 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ret_003(request: FeatureRequest) -> FeatureResult:
    """[RET-003] Hybrid Search 설정.

    Keyword와 Vector 검색 결합 정책을 설정한다.
    """
    raise NotImplementedError("[RET-003] 기능 구현이 필요합니다.")
