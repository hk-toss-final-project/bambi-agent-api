"""기능 구현 모듈.

WC-011, WC-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wc_011(request: FeatureRequest) -> FeatureResult:
    """[WC-011] 작업 Timeout.

    지정된 시간 이상 실행되는 작업을 종료한다.
    """
    raise NotImplementedError("[WC-011] 기능 구현이 필요합니다.")


async def wc_012(request: FeatureRequest) -> FeatureResult:
    """[WC-012] 작업 취소.

    취소 요청이 들어온 작업을 중단한다.
    """
    raise NotImplementedError("[WC-012] 기능 구현이 필요합니다.")
