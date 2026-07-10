"""기능 구현 모듈.

WC-003, WC-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wc_003(request: FeatureRequest) -> FeatureResult:
    """[WC-003] Worker Heartbeat.

    Worker의 생존 상태를 기록한다.
    """
    raise NotImplementedError("[WC-003] 기능 구현이 필요합니다.")


async def wc_004(request: FeatureRequest) -> FeatureResult:
    """[WC-004] Worker 상태 조회.

    Worker별 실행 상태와 처리량을 조회한다.
    """
    raise NotImplementedError("[WC-004] 기능 구현이 필요합니다.")
