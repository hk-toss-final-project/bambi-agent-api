"""기능 구현 모듈.

SYS-012 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sys_012(request: FeatureRequest) -> FeatureResult:
    """[SYS-012] Graceful Shutdown.

    진행 중 요청을 정리하고 안전하게 종료한다.
    """
    raise NotImplementedError("[SYS-012] 기능 구현이 필요합니다.")
