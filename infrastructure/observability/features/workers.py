"""기능 구현 모듈.

OBS-016 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obs_016(request: FeatureRequest) -> FeatureResult:
    """[OBS-016] Worker Heartbeat 모니터링.

    Worker 생존 상태를 감시한다.
    """
    raise NotImplementedError("[OBS-016] 기능 구현이 필요합니다.")
