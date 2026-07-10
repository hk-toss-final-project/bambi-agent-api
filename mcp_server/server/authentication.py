"""기능 구현 모듈.

MCP-003, MCP-009, MCP-010, MCP-011 기능의 실제 구현 위치를 제공한다.
"""

from shared.contracts import FeatureRequest, FeatureResult


async def mcp_003(request: FeatureRequest) -> FeatureResult:
    """[MCP-003] MCP 인증.

    API Key 또는 사용자 권한을 검증한다.
    """
    raise NotImplementedError("[MCP-003] 기능 구현이 필요합니다.")


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
