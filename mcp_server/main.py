"""Personal Wiki를 외부 Agent에 제공하는 MCP Streamable HTTP 서버."""

import asyncio
from typing import Annotated
from urllib.parse import urlsplit

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl, Field
from starlette.applications import Starlette

from app.config import Settings, load_settings
from app.dependencies import AppContainer, create_container
from mcp_server.server.api import (
    McpApiKeyVerifier,
    McpBearerTokenVerifier,
    McpOAuthTokenVerifier,
)
from mcp_server.tools.api import (
    WikiFetchOutput,
    WikiSearchOutput,
    mcptool_001,
    mcptool_002,
)


def build_mcp_server(settings: Settings, container: AppContainer) -> MCPServer:
    """API Key 인증과 Personal Wiki `search`·`fetch` 도구를 등록한다."""
    api_key_verifier = (
        McpApiKeyVerifier(container.mcp_api_key_repository)
        if container.mcp_api_key_repository is not None
        else None
    )
    oauth_verifier = None
    if settings.internal_api_token is not None:
        oauth_verifier = McpOAuthTokenVerifier(
            service_api_base_url=settings.service_api_base_url,
            introspection_path=settings.mcp_oauth_introspection_path,
            internal_token=settings.internal_api_token.get_secret_value(),
            resource_url=settings.mcp_server_url,
            timeout_seconds=settings.mcp_oauth_timeout_seconds,
        )
    verifier = McpBearerTokenVerifier(api_key_verifier, oauth_verifier)
    server = MCPServer(
        name="bambi-personal-wiki",
        title="Bambi LLM Wiki",
        description="사용자가 저장한 개인 LLM Wiki를 검색하고 읽습니다.",
        instructions=(
            "반드시 search로 관련 문서를 찾은 뒤 fetch로 본문을 읽으세요. "
            "결과는 API Key에 연결된 사용자 Wiki로 제한됩니다."
        ),
        version=settings.app_version,
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.mcp_auth_issuer_url),
            resource_server_url=AnyHttpUrl(settings.mcp_server_url),
            required_scopes=["wiki:read"],
        ),
    )

    @server.tool(
        name="search",
        title="개인 LLM Wiki 검색",
        description="API Key 소유자의 개인 Wiki에서 관련 문서를 검색합니다.",
    )
    async def search(
        query: Annotated[str, Field(min_length=1, max_length=500)],
        ctx: Context,
        limit: Annotated[int, Field(ge=1, le=20)] = 10,
    ) -> WikiSearchOutput:
        """검색어와 일치하는 개인 Wiki 문서 요약을 반환한다."""
        user_id = _authenticated_user_id()
        reader = _wiki_reader(container)
        return await mcptool_001(
            reader,
            user_id=user_id,
            query=query,
            limit=limit,
        )

    @server.tool(
        name="fetch",
        title="개인 LLM Wiki 문서 읽기",
        description="search가 반환한 문서 ID로 Markdown 본문과 출처를 조회합니다.",
    )
    async def fetch(
        id: Annotated[str, Field(min_length=1, max_length=128)],
        ctx: Context,
    ) -> WikiFetchOutput:
        """인증 사용자 Namespace의 Wiki 문서 Markdown을 반환한다."""
        user_id = _authenticated_user_id()
        reader = _wiki_reader(container)
        return await mcptool_002(reader, user_id=user_id, document_id=id)

    return server


def build_mcp_http_app(server: MCPServer, settings: Settings) -> Starlette:
    """공개 Host를 제한한 Stateless Streamable HTTP ASGI 앱을 만든다."""
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
        transport_security=_transport_security(settings),
    )


def _transport_security(settings: Settings) -> TransportSecuritySettings:
    """설정된 공개 URL의 Host·Origin만 허용하는 DNS 재바인딩 정책을 만든다."""
    resource_url = urlsplit(settings.mcp_server_url)
    allowed_host = resource_url.netloc
    origin = f"{resource_url.scheme}://{allowed_host}"
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[allowed_host],
        allowed_origins=[origin],
    )


def _authenticated_user_id() -> str:
    """MCP SDK 인증 Context에서 Personal Wiki 사용자 ID를 반환한다."""
    token = get_access_token()
    if token is None or token.subject is None or "wiki:read" not in token.scopes:
        raise PermissionError("Personal Wiki 인증 정보가 없습니다.")
    return token.subject


def _wiki_reader(container: AppContainer) -> object:
    """MCP Tool이 사용할 Personal Wiki 저장소를 반환한다."""
    if container.wiki_graph_repository is None:
        raise RuntimeError("Personal Wiki 저장소가 준비되지 않았습니다.")
    return container.wiki_graph_repository


async def _run() -> None:
    """MCP 서버만 단독으로 실행하고 Agent DB 수명 주기를 관리한다."""
    settings = load_settings()
    container = create_container(settings)
    await container.startup()
    server = build_mcp_server(settings, container)
    try:
        await server.run_streamable_http_async(
            host="0.0.0.0",
            port=8000,
            streamable_http_path="/mcp",
            json_response=True,
            stateless_http=True,
            transport_security=_transport_security(settings),
        )
    finally:
        shutdown_task = asyncio.create_task(container.shutdown())
        try:
            await asyncio.shield(shutdown_task)
        except asyncio.CancelledError:
            await shutdown_task
            raise


def main() -> None:
    """외부 Agent 연결용 MCP 서버를 단독 프로세스로 실행한다."""
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
