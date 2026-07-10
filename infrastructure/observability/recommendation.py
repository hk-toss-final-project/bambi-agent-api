"""기능 구현 모듈.

OBS-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def obs_011(request: FeatureRequest) -> FeatureResult:
    """[OBS-011] Recommendation 로그.

    추천 후보와 점수 계산 결과를 기록한다.
    """
    raise NotImplementedError("[OBS-011] 기능 구현이 필요합니다.")
