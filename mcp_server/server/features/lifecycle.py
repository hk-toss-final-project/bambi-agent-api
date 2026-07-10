"""기능 구현 모듈.

MCP-001, MCP-002 기능의 실제 구현 위치를 제공한다.
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
