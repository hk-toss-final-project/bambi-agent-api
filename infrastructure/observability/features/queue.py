"""기능 구현 모듈.

OBS-015 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obs_015(request: FeatureRequest) -> FeatureResult:
    """[OBS-015] Queue Backlog 모니터링.

    대기 작업과 처리 지연을 감시한다.
    """
    raise NotImplementedError("[OBS-015] 기능 구현이 필요합니다.")
