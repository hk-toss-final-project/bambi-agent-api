"""기능 구현 모듈.

WC-006, WC-007, WC-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wc_006(request: FeatureRequest) -> FeatureResult:
    """[WC-006] Retry 정책.

    재시도 가능한 오류에 재처리 정책을 적용한다.
    """
    raise NotImplementedError("[WC-006] 기능 구현이 필요합니다.")


async def wc_007(request: FeatureRequest) -> FeatureResult:
    """[WC-007] Exponential Backoff.

    재시도 간격을 점진적으로 증가시킨다.
    """
    raise NotImplementedError("[WC-007] 기능 구현이 필요합니다.")


async def wc_008(request: FeatureRequest) -> FeatureResult:
    """[WC-008] Dead Letter Queue.

    반복 실패 작업을 격리한다.
    """
    raise NotImplementedError("[WC-008] 기능 구현이 필요합니다.")
