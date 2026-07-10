"""기능 구현 모듈.

OBS-022 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obs_022(request: FeatureRequest) -> FeatureResult:
    """[OBS-022] 장애 Alert.

    Queue 적체, Provider 장애, 반복 실패를 알린다.
    """
    raise NotImplementedError("[OBS-022] 기능 구현이 필요합니다.")
