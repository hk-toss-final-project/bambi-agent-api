"""MCP Bearer API Key·Scope·사용자 Wiki 권한 검증 기능."""

from datetime import UTC, datetime
from typing import Any

import httpx

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


class McpOAuthTokenVerifier(TokenVerifier):
    """Service API가 발급한 opaque OAuth access token을 내부 introspection으로 검증한다."""

    def __init__(
        self,
        *,
        service_api_base_url: str,
        introspection_path: str,
        internal_token: str,
        resource_url: str,
        timeout_seconds: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = f"{service_api_base_url.rstrip('/')}{introspection_path}"
        self._internal_token = internal_token
        self._resource_url = resource_url
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def verify_token(self, token: str) -> AccessToken | None:
        """활성·audience·scope·만료를 모두 통과한 access token만 MCP 주체로 바꾼다."""
        if (
            not token.startswith("bmb_oauth_")
            or len(token) > 512
            or not self._internal_token
        ):
            return None
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._internal_token}"},
                    json={"token": token},
                )
            if response.status_code != 200:
                return None
            payload: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            return None

        scopes = str(payload.get("scope") or "").split()
        subject = payload.get("sub")
        client_id = payload.get("client_id")
        expires_at = payload.get("exp")
        if (
            payload.get("active") is not True
            or payload.get("aud") != self._resource_url
            or "wiki:read" not in scopes
            or not isinstance(subject, str)
            or not isinstance(client_id, str)
            or not isinstance(expires_at, int)
            or expires_at <= int(datetime.now(UTC).timestamp())
        ):
            return None
        return AccessToken(
            token="oauth:" + client_id,
            client_id=client_id,
            subject=subject,
            scopes=scopes,
            expires_at=expires_at,
        )


class McpBearerTokenVerifier(TokenVerifier):
    """기존 API Key와 UI용 OAuth access token을 같은 MCP Bearer 경계에서 검증한다."""

    def __init__(
        self,
        api_key_verifier: McpApiKeyVerifier | None,
        oauth_verifier: McpOAuthTokenVerifier | None,
    ) -> None:
        self._api_key_verifier = api_key_verifier
        self._oauth_verifier = oauth_verifier

    async def verify_token(self, token: str) -> AccessToken | None:
        if self._api_key_verifier is not None:
            access_token = await self._api_key_verifier.verify_token(token)
            if access_token is not None:
                return access_token
        if self._oauth_verifier is not None:
            return await self._oauth_verifier.verify_token(token)
        return None
