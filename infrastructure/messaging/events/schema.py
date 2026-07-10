"""기능 구현 모듈.

EVT-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def evt_008(request: FeatureRequest) -> FeatureResult:
    """[EVT-008] Event Schema Version 관리.

    이벤트 구조의 버전을 관리한다.
    """
    raise NotImplementedError("[EVT-008] 기능 구현이 필요합니다.")
