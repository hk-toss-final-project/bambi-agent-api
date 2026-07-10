"""기능 구현 모듈.

WBA-015 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wba_015(request: FeatureRequest) -> FeatureResult:
    """[WBA-015] Wiki 삭제 반영.

    삭제된 사용자 원천과 파생 데이터를 제거한다.
    """
    raise NotImplementedError("[WBA-015] 기능 구현이 필요합니다.")
