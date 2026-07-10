"""기능 구현 모듈.

SYS-007, SYS-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sys_007(request: FeatureRequest) -> FeatureResult:
    """[SYS-007] 공통 예외 처리.

    API 전역의 오류 응답 형식을 통일한다.
    """
    raise NotImplementedError("[SYS-007] 기능 구현이 필요합니다.")


async def sys_008(request: FeatureRequest) -> FeatureResult:
    """[SYS-008] 요청 추적.

    Request ID와 Trace ID를 생성하고 전달한다.
    """
    raise NotImplementedError("[SYS-008] 기능 구현이 필요합니다.")
