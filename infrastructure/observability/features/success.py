"""기능 구현 모듈.

OBS-017, OBS-018 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obs_017(request: FeatureRequest) -> FeatureResult:
    """[OBS-017] 작업 성공률 모니터링.

    작업 유형별 성공률을 집계한다.
    """
    raise NotImplementedError("[OBS-017] 기능 구현이 필요합니다.")


async def obs_018(request: FeatureRequest) -> FeatureResult:
    """[OBS-018] 작업 실패율 모니터링.

    실패와 재시도 비율을 집계한다.
    """
    raise NotImplementedError("[OBS-018] 기능 구현이 필요합니다.")
