"""기능 구현 모듈.

WC-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wc_005(request: FeatureRequest) -> FeatureResult:
    """[WC-005] 작업 진행률 기록.

    장시간 작업의 처리 단계를 기록한다.
    """
    raise NotImplementedError("[WC-005] 기능 구현이 필요합니다.")
