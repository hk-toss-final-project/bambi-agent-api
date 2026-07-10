"""기능 구현 모듈.

WC-016, WC-017 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wc_016(request: FeatureRequest) -> FeatureResult:
    """[WC-016] Worker 로그.

    작업 실행과 오류 정보를 기록한다.
    """
    raise NotImplementedError("[WC-016] 기능 구현이 필요합니다.")


async def wc_017(request: FeatureRequest) -> FeatureResult:
    """[WC-017] Trace Context 전달.

    API 요청부터 Worker와 Provider까지 추적 정보를 유지한다.
    """
    raise NotImplementedError("[WC-017] 기능 구현이 필요합니다.")
