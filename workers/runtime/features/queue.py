"""기능 구현 모듈.

WC-001, WC-002 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def wc_001(request: FeatureRequest) -> FeatureResult:
    """[WC-001] Queue Job Consume.

    Queue에서 처리할 작업을 가져온다.
    """
    raise NotImplementedError("[WC-001] 기능 구현이 필요합니다.")


async def wc_002(request: FeatureRequest) -> FeatureResult:
    """[WC-002] Job Claim.

    하나의 Worker가 작업을 점유한다.
    """
    raise NotImplementedError("[WC-002] 기능 구현이 필요합니다.")
