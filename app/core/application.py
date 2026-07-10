"""기능 구현 모듈.

SYS-001, SYS-002, SYS-003 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sys_001(request: FeatureRequest) -> FeatureResult:
    """[SYS-001] 애플리케이션 초기화.

    Agent API 실행에 필요한 설정과 컴포넌트를 초기화한다.
    """
    raise NotImplementedError("[SYS-001] 기능 구현이 필요합니다.")


async def sys_002(request: FeatureRequest) -> FeatureResult:
    """[SYS-002] API 라우터 등록.

    내부 API, 외부 API, 관리자 API 라우터를 등록한다.
    """
    raise NotImplementedError("[SYS-002] 기능 구현이 필요합니다.")


async def sys_003(request: FeatureRequest) -> FeatureResult:
    """[SYS-003] 환경 설정 로딩.

    환경별 설정과 Secret 참조 정보를 로딩한다.
    """
    raise NotImplementedError("[SYS-003] 기능 구현이 필요합니다.")
