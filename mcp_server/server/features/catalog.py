"""기능 구현 모듈.

MCP-004, MCP-005 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


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
