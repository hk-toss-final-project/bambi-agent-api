"""기능 구현 모듈.

WC-015 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wc_015(request: FeatureRequest) -> FeatureResult:
    """[WC-015] Graceful Shutdown.

    진행 중 작업을 정리하고 안전하게 종료한다.
    """
    raise NotImplementedError("[WC-015] 기능 구현이 필요합니다.")
