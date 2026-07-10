"""기능 구현 모듈.

WBA-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wba_011(request: FeatureRequest) -> FeatureResult:
    """[WBA-011] Wiki 재임베딩.

    변경된 문서와 구조의 Embedding을 갱신한다.
    """
    raise NotImplementedError("[WBA-011] 기능 구현이 필요합니다.")
