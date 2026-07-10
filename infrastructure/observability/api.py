"""기능 구현 모듈.

OBS-001 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obs_001(request: FeatureRequest) -> FeatureResult:
    """[OBS-001] API 요청 로그.

    Agent API 요청과 응답 상태를 기록한다.
    """
    raise NotImplementedError("[OBS-001] 기능 구현이 필요합니다.")
