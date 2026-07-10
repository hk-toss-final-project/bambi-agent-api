"""기능 구현 모듈.

SEC-001 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sec_001(request: FeatureRequest) -> FeatureResult:
    """[SEC-001] Agent API Network 격리.

    Internal Agent API를 외부 네트워크에서 차단한다.
    """
    raise NotImplementedError("[SEC-001] 기능 구현이 필요합니다.")
