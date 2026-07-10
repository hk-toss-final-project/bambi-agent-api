"""기능 구현 모듈.

OBS-010 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obs_010(request: FeatureRequest) -> FeatureResult:
    """[OBS-010] Image Generation 로그.

    이미지 생성 요청과 결과를 기록한다.
    """
    raise NotImplementedError("[OBS-010] 기능 구현이 필요합니다.")
