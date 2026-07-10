"""기능 구현 모듈.

AUTH-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def auth_005(request: FeatureRequest) -> FeatureResult:
    """[AUTH-005] Scope 기반 권한 검증.

    호출 주체별 허용 기능 범위를 검증한다.
    """
    raise NotImplementedError("[AUTH-005] 기능 구현이 필요합니다.")
