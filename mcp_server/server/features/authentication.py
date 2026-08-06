"""MCP Bearer API Key·Scope·사용자 Wiki 권한 검증 기능."""

from datetime import UTC, datetime

from mcp.server.auth.provider import AccessToken, TokenVerifier

from app.security.api_keys.api import (
    ApiKeyAuthorizationRepository,
    ApiKeyPrincipal,
    key_014,
)
from shared.contracts import FeatureRequest, FeatureResult


async def mcp_003(
    repository: ApiKeyAuthorizationRepository, raw_key: str
) -> ApiKeyPrincipal | None:
    """[MCP-003] MCP 인증.

    Bearer API Key를 검증하고 연결된 Personal Wiki 주체를 반환한다.
    """
    return await key_014(repository, raw_key=raw_key, now=datetime.now(UTC))


async def mcp_009(principal: ApiKeyPrincipal, required_scope: str) -> bool:
    """[MCP-009] MCP Scope 검증.

    Tool별 필요한 권한을 검증한다.
    """
    return required_scope in principal.scopes


async def mcp_010(request: FeatureRequest) -> FeatureResult:
    """[MCP-010] MCP Quota 적용.

    API Key별 호출량과 Token 제한을 적용한다.
    """
    raise NotImplementedError("[MCP-010] 기능 구현이 필요합니다.")


async def mcp_011(principal: ApiKeyPrincipal) -> str:
    """[MCP-011] MCP 사용자 권한 검증.

    Personal Wiki 접근 범위를 Key에 연결된 사용자 ID로 강제한다.
    """
    if not await mcp_009(principal, "wiki:read"):
        raise PermissionError("Personal Wiki 읽기 Scope가 없습니다.")
    return principal.user_id


class McpApiKeyVerifier(TokenVerifier):
    """MCP SDK의 Bearer 인증을 Bambi API Key 저장소에 연결한다."""

    def __init__(self, repository: ApiKeyAuthorizationRepository) -> None:
        """검증에 사용할 API Key 저장소를 주입한다."""
        self._repository = repository

    async def verify_token(self, token: str) -> AccessToken | None:
        """유효한 Bambi API Key를 MCP SDK Access Token 정보로 변환한다."""
        principal = await mcp_003(self._repository, token)
        if principal is None:
            return None
        return AccessToken(
            # 원문 Secret을 요청 Context에 남기지 않고 검증된 Key ID만 보존한다.
            token=principal.key_id,
            client_id=principal.key_id,
            subject=principal.user_id,
            scopes=list(principal.scopes),
            expires_at=(
                int(principal.expires_at.timestamp())
                if principal.expires_at is not None
                else None
            ),
        )
