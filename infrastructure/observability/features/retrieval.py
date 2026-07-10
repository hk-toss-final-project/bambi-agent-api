"""기능 구현 모듈.

OBS-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obs_008(request: FeatureRequest) -> FeatureResult:
    """[OBS-008] Retrieval 로그.

    개인 Wiki와 Global Source 검색 결과를 기록한다.
    """
    raise NotImplementedError("[OBS-008] 기능 구현이 필요합니다.")
