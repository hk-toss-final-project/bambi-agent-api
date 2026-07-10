"""기능 구현 모듈.

EVT-003 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def evt_003(request: FeatureRequest) -> FeatureResult:
    """[EVT-003] Global Source Collected 이벤트.

    외부 Source 수집 완료 사실을 전달한다.
    """
    raise NotImplementedError("[EVT-003] 기능 구현이 필요합니다.")
