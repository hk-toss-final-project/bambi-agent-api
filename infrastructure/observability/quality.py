"""기능 구현 모듈.

OBS-019, OBS-020 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obs_019(request: FeatureRequest) -> FeatureResult:
    """[OBS-019] 콘텐츠 품질 지표.

    품질 통과, 재생성, 거절 비율을 집계한다.
    """
    raise NotImplementedError("[OBS-019] 기능 구현이 필요합니다.")


async def obs_020(request: FeatureRequest) -> FeatureResult:
    """[OBS-020] Wiki 품질 지표.

    중복률, 문서 수, Build 실패율을 집계한다.
    """
    raise NotImplementedError("[OBS-020] 기능 구현이 필요합니다.")
