"""기능 구현 모듈.

MCP-008 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def mcp_008(request: FeatureRequest) -> FeatureResult:
    """[MCP-008] MCP 호출 로그.

    Tool 호출과 결과를 기록한다.
    """
    raise NotImplementedError("[MCP-008] 기능 구현이 필요합니다.")
