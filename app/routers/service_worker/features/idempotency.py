"""기능 구현 모듈.

SW-011, SW-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sw_011(request: FeatureRequest) -> FeatureResult:
    """[SW-011] 이벤트 중복 처리 방지.

    동일 이벤트가 여러 번 반영되지 않도록 한다.
    """
    raise NotImplementedError("[SW-011] 기능 구현이 필요합니다.")


async def sw_012(request: FeatureRequest) -> FeatureResult:
    """[SW-012] 오래된 이벤트 무시.

    최신 버전보다 오래된 이벤트를 무시한다.
    """
    raise NotImplementedError("[SW-012] 기능 구현이 필요합니다.")
