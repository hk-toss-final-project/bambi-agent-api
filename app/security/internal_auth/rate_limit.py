"""기능 구현 모듈.

AUTH-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def auth_007(request: FeatureRequest) -> FeatureResult:
    """[AUTH-007] 내부 Rate Limit.

    내부 호출 주체별 요청량을 제한한다.
    """
    raise NotImplementedError("[AUTH-007] 기능 구현이 필요합니다.")
