"""MCP OAuth access token introspection 경계를 검증한다."""

import asyncio
from datetime import UTC, datetime

import httpx

from mcp_server.server.api import McpOAuthTokenVerifier


def _transport(payload: dict[str, object], *, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://service-api:8080/internal/oauth/introspect"
        assert request.headers["Authorization"] == "Bearer internal-token"
        return httpx.Response(status_code, json=payload, request=request)

    return httpx.MockTransport(handler)


def test_oauth_access_token_accepts_active_wiki_principal() -> None:
    """활성 token의 subject·client·scope가 MCP AccessToken으로 전달된다."""
    expires_at = int(datetime.now(UTC).timestamp()) + 300
    verifier = McpOAuthTokenVerifier(
        service_api_base_url="http://service-api:8080",
        introspection_path="/internal/oauth/introspect",
        internal_token="internal-token",
        resource_url="https://bambi.example/mcp",
        transport=_transport(
            {
                "active": True,
                "sub": "42",
                "client_id": "bmb_client_chatgpt",
                "scope": "wiki:read",
                "exp": expires_at,
                "aud": "https://bambi.example/mcp",
            }
        ),
    )

    token = asyncio.run(verifier.verify_token("bmb_oauth_access-token"))

    assert token is not None
    assert token.subject == "42"
    assert token.client_id == "bmb_client_chatgpt"
    assert token.scopes == ["wiki:read"]
    assert token.expires_at == expires_at
    assert token.token == "oauth:bmb_client_chatgpt"


def test_oauth_access_token_rejects_wrong_audience_or_failed_introspection() -> None:
    """다른 MCP용 token과 Service API 오류는 인증 실패로 닫힌다."""
    expires_at = int(datetime.now(UTC).timestamp()) + 300
    wrong_audience = McpOAuthTokenVerifier(
        service_api_base_url="http://service-api:8080",
        introspection_path="/internal/oauth/introspect",
        internal_token="internal-token",
        resource_url="https://bambi.example/mcp",
        transport=_transport(
            {
                "active": True,
                "sub": "42",
                "client_id": "client",
                "scope": "wiki:read",
                "exp": expires_at,
                "aud": "https://other.example/mcp",
            }
        ),
    )
    unavailable = McpOAuthTokenVerifier(
        service_api_base_url="http://service-api:8080",
        introspection_path="/internal/oauth/introspect",
        internal_token="internal-token",
        resource_url="https://bambi.example/mcp",
        transport=_transport({}, status_code=503),
    )

    assert asyncio.run(wrong_audience.verify_token("bmb_oauth_access-token")) is None
    assert asyncio.run(unavailable.verify_token("bmb_oauth_access-token")) is None


def test_non_oauth_token_does_not_call_introspection() -> None:
    """API Key 등 다른 Bearer 형식은 Service API로 전달하지 않는다."""
    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError("introspection must not be called")

    verifier = McpOAuthTokenVerifier(
        service_api_base_url="http://service-api:8080",
        introspection_path="/internal/oauth/introspect",
        internal_token="internal-token",
        resource_url="https://bambi.example/mcp",
        transport=httpx.MockTransport(unexpected),
    )

    assert asyncio.run(verifier.verify_token("bmb_mcp_key")) is None
