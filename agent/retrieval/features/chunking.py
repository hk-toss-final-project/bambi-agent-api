"""기능 구현 모듈.

RET-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def ret_006(request: FeatureRequest) -> FeatureResult:
    """[RET-006] Chunk 설정.

    문서 분할 크기와 중첩 기준을 설정한다.
    """
    raise NotImplementedError("[RET-006] 기능 구현이 필요합니다.")
