"""기능 구현 모듈.

SYS-004, SYS-005, SYS-006 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sys_004(request: FeatureRequest) -> FeatureResult:
    """[SYS-004] DB 연결 관리.

    Agent DB와 Vector 저장소 연결을 관리한다.
    """
    raise NotImplementedError("[SYS-004] 기능 구현이 필요합니다.")


async def sys_005(request: FeatureRequest) -> FeatureResult:
    """[SYS-005] Queue 연결 관리.

    Job Queue와 Event Bus 연결을 관리한다.
    """
    raise NotImplementedError("[SYS-005] 기능 구현이 필요합니다.")


async def sys_006(request: FeatureRequest) -> FeatureResult:
    """[SYS-006] 외부 Provider 연결 관리.

    LLM, Embedding, 이미지 Provider 연결을 관리한다.
    """
    raise NotImplementedError("[SYS-006] 기능 구현이 필요합니다.")
