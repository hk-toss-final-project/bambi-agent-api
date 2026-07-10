"""MCP Server 기능 스캐폴드.

전체 기능 명세의 각 기능 ID를 구현할 비동기 함수 계약을 정의한다.
현재 함수 본문은 의도적으로 구현하지 않은 상태이다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def mcp_001(request: FeatureRequest) -> FeatureResult:
    """[MCP-001] MCP Server 실행.

    외부 Agent 연결을 위한 MCP 서버를 실행한다.
    """
    raise NotImplementedError("[MCP-001] 기능 구현이 필요합니다.")


async def mcp_002(request: FeatureRequest) -> FeatureResult:
    """[MCP-002] MCP 연결 관리.

    MCP Client 연결과 세션을 관리한다.
    """
    raise NotImplementedError("[MCP-002] 기능 구현이 필요합니다.")


async def mcp_003(request: FeatureRequest) -> FeatureResult:
    """[MCP-003] MCP 인증.

    API Key 또는 사용자 권한을 검증한다.
    """
    raise NotImplementedError("[MCP-003] 기능 구현이 필요합니다.")


async def mcp_004(request: FeatureRequest) -> FeatureResult:
    """[MCP-004] MCP Tool 목록 제공.

    사용 가능한 Tool 목록을 반환한다.
    """
    raise NotImplementedError("[MCP-004] 기능 구현이 필요합니다.")


async def mcp_005(request: FeatureRequest) -> FeatureResult:
    """[MCP-005] MCP Tool Schema 제공.

    각 Tool의 입력과 출력 Schema를 제공한다.
    """
    raise NotImplementedError("[MCP-005] 기능 구현이 필요합니다.")


async def mcp_006(request: FeatureRequest) -> FeatureResult:
    """[MCP-006] MCP Tool 실행.

    외부 Agent가 요청한 Tool을 실행한다.
    """
    raise NotImplementedError("[MCP-006] 기능 구현이 필요합니다.")


async def mcp_007(request: FeatureRequest) -> FeatureResult:
    """[MCP-007] MCP 비동기 Job 지원.

    긴 작업에 Job ID를 반환한다.
    """
    raise NotImplementedError("[MCP-007] 기능 구현이 필요합니다.")


async def mcp_008(request: FeatureRequest) -> FeatureResult:
    """[MCP-008] MCP 호출 로그.

    Tool 호출과 결과를 기록한다.
    """
    raise NotImplementedError("[MCP-008] 기능 구현이 필요합니다.")


async def mcp_009(request: FeatureRequest) -> FeatureResult:
    """[MCP-009] MCP Scope 검증.

    Tool별 필요한 권한을 검증한다.
    """
    raise NotImplementedError("[MCP-009] 기능 구현이 필요합니다.")


async def mcp_010(request: FeatureRequest) -> FeatureResult:
    """[MCP-010] MCP Quota 적용.

    API Key별 호출량과 Token 제한을 적용한다.
    """
    raise NotImplementedError("[MCP-010] 기능 구현이 필요합니다.")


async def mcp_011(request: FeatureRequest) -> FeatureResult:
    """[MCP-011] MCP 사용자 권한 검증.

    Personal Wiki 접근에 사용자 승인이 있는지 확인한다.
    """
    raise NotImplementedError("[MCP-011] 기능 구현이 필요합니다.")
