"""기능 구현 모듈.

SYS-009, SYS-010, SYS-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sys_009(request: FeatureRequest) -> FeatureResult:
    """[SYS-009] Liveness Check.

    Agent API 프로세스 생존 여부를 확인한다.
    """
    raise NotImplementedError("[SYS-009] 기능 구현이 필요합니다.")


async def sys_010(request: FeatureRequest) -> FeatureResult:
    """[SYS-010] Readiness Check.

    DB, Queue, Provider의 요청 처리 가능 상태를 확인한다.
    """
    raise NotImplementedError("[SYS-010] 기능 구현이 필요합니다.")


async def sys_011(request: FeatureRequest) -> FeatureResult:
    """[SYS-011] Version 조회.

    API와 주요 설정 버전을 반환한다.
    """
    raise NotImplementedError("[SYS-011] 기능 구현이 필요합니다.")
