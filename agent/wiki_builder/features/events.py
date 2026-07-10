"""기능 구현 모듈.

WBA-016 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wba_016(request: FeatureRequest) -> FeatureResult:
    """[WBA-016] Wiki Build 완료 이벤트.

    개인 Wiki 갱신 완료 사실을 이벤트로 발행한다.
    """
    raise NotImplementedError("[WBA-016] 기능 구현이 필요합니다.")
