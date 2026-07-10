"""기능 구현 모듈.

MCP-006, MCP-007 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


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
