"""기능 구현 모듈.

WSE-009 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wse_009(request: FeatureRequest) -> FeatureResult:
    """[WSE-009] Wiki Source 삭제 이벤트 수신.

    사용자가 제거한 Wiki 원천을 반영한다.
    """
    raise NotImplementedError("[WSE-009] 기능 구현이 필요합니다.")
