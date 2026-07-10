"""기능 구현 모듈.

OBS-021 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obs_021(request: FeatureRequest) -> FeatureResult:
    """[OBS-021] 분산 Trace.

    Service부터 Agent Worker와 Provider까지 추적한다.
    """
    raise NotImplementedError("[OBS-021] 기능 구현이 필요합니다.")
