"""기능 구현 모듈.

SEC-002, SEC-012, SEC-013 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def sec_002(request: FeatureRequest) -> FeatureResult:
    """[SEC-002] Internal API 인증.

    승인된 Service와 Worker만 접근하도록 한다.
    """
    raise NotImplementedError("[SEC-002] 기능 구현이 필요합니다.")


async def sec_012(request: FeatureRequest) -> FeatureResult:
    """[SEC-012] 관리자 권한 검증.

    관리 기능별 세부 관리자 권한을 검증한다.
    """
    raise NotImplementedError("[SEC-012] 기능 구현이 필요합니다.")


async def sec_013(request: FeatureRequest) -> FeatureResult:
    """[SEC-013] API Scope 최소 권한.

    외부 Key와 MCP Tool에 최소 권한만 부여한다.
    """
    raise NotImplementedError("[SEC-013] 기능 구현이 필요합니다.")
