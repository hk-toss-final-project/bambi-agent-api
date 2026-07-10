"""기능 구현 모듈.

AUTH-004 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def auth_004(request: FeatureRequest) -> FeatureResult:
    """[AUTH-004] 호출 주체 식별.

    service-api, service-worker, scheduler 등 호출 주체를 구분한다.
    """
    raise NotImplementedError("[AUTH-004] 기능 구현이 필요합니다.")
