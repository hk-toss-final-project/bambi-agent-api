"""기능 구현 모듈.

AUTH-001, AUTH-002, AUTH-003 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def auth_001(request: FeatureRequest) -> FeatureResult:
    """[AUTH-001] Service API 인증.

    service-api의 내부 호출 권한을 검증한다.
    """
    raise NotImplementedError("[AUTH-001] 기능 구현이 필요합니다.")


async def auth_002(request: FeatureRequest) -> FeatureResult:
    """[AUTH-002] Service Worker 인증.

    service-worker의 내부 호출 권한을 검증한다.
    """
    raise NotImplementedError("[AUTH-002] 기능 구현이 필요합니다.")


async def auth_003(request: FeatureRequest) -> FeatureResult:
    """[AUTH-003] Scheduler 인증.

    scheduler의 작업 등록 권한을 검증한다.
    """
    raise NotImplementedError("[AUTH-003] 기능 구현이 필요합니다.")
