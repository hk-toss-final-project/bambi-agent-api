"""기능 구현 모듈.

EVT-001, EVT-002 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def evt_001(request: FeatureRequest) -> FeatureResult:
    """[EVT-001] User Wiki Updated 이벤트.

    개인 Wiki 갱신 완료 사실을 전달한다.
    """
    raise NotImplementedError("[EVT-001] 기능 구현이 필요합니다.")


async def evt_002(request: FeatureRequest) -> FeatureResult:
    """[EVT-002] User Interest Updated 이벤트.

    사용자 관심사 프로필 갱신을 전달한다.
    """
    raise NotImplementedError("[EVT-002] 기능 구현이 필요합니다.")
