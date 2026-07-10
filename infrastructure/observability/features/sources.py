"""기능 구현 모듈.

OBS-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obs_005(request: FeatureRequest) -> FeatureResult:
    """[OBS-005] Global Source 수집 로그.

    Source별 수집 결과와 오류를 기록한다.
    """
    raise NotImplementedError("[OBS-005] 기능 구현이 필요합니다.")
