"""기능 구현 모듈.

OBS-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obs_007(request: FeatureRequest) -> FeatureResult:
    """[OBS-007] Generation 로그.

    콘텐츠 생성 과정과 사용 모델을 기록한다.
    """
    raise NotImplementedError("[OBS-007] 기능 구현이 필요합니다.")
