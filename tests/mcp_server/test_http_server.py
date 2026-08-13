"""MCP Streamable HTTP의 Bearer 인증과 Tool 호출을 검증한다."""

import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import AppContainer
from app.security.api_keys.api import key_008
from mcp_server.main import build_mcp_http_app, build_mcp_server
from mcp_server import main as mcp_main
from tests.mcp_server.tools.test_personal_wiki import _FakeWikiReader, _FakeWikiWriter


class _FakeMcpApiKeyRepository:
    """MCP HTTP 인증에 사용할 단일 API Key 저장소 대역."""

    def __init__(self, raw_key: str, *, scopes: list[str] | None = None) -> None:
        """원문 Key의 Prefix와 Hash만 검증 레코드로 보존한다."""
        generated = asyncio.run(key_008(raw_key))
        self.record = {
            "id": "11111111-1111-1111-1111-111111111111",
            "key_prefix": generated.key_prefix,
            "key_hash": generated.key_hash,
            "principal_id": "42",
            "scopes": scopes or ["wiki:read"],
            "status": "active",
            "expires_at": None,
        }

    async def startup(self) -> None:
        """인메모리 저장소라 시작 작업을 하지 않는다."""

    async def shutdown(self) -> None:
        """인메모리 저장소라 종료 작업을 하지 않는다."""

    async def find_api_key_by_prefix(self, key_prefix: str) -> dict[str, object] | None:
        """등록 Prefix와 일치하는 검증 레코드를 반환한다."""
        return self.record if self.record["key_prefix"] == key_prefix else None

    async def mark_api_key_used(self, key_id: str) -> None:
        """검증 성공 시각 갱신을 생략한다."""


class _FakeMcpWikiRepository(_FakeWikiReader, _FakeWikiWriter):
    """Container 수명 주기를 지원하는 Wiki 읽기·쓰기 저장소 대역."""

    def __init__(self) -> None:
        """읽기·쓰기 대역의 호출 기록을 모두 초기화한다."""
        _FakeWikiReader.__init__(self)
        _FakeWikiWriter.__init__(self)

    async def startup(self) -> None:
        """인메모리 저장소라 시작 작업을 하지 않는다."""

    async def shutdown(self) -> None:
        """인메모리 저장소라 종료 작업을 하지 않는다."""


def _meta() -> dict[str, object]:
    """2026-07-28 MCP 요청에 필요한 Client Metadata를 만든다."""
    return {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "1"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }


def _client(raw_key: str, *, scopes: list[str] | None = None) -> TestClient:
    """MCP 인증·Wiki 대역이 연결된 전용 MCP TestClient를 만든다."""
    settings = Settings(
        environment="test",
        mcp_server_url="http://testserver/mcp",
        mcp_auth_issuer_url="http://testserver",
    )
    container = AppContainer(
        settings=settings,
        mcp_api_key_repository=_FakeMcpApiKeyRepository(raw_key, scopes=scopes),
        wiki_graph_repository=_FakeMcpWikiRepository(),
    )
    server = build_mcp_server(settings, container)
    return TestClient(build_mcp_http_app(server, settings))


def _headers(raw_key: str, method: str, *, name: str | None = None) -> dict[str, str]:
    """MCP Streamable HTTP 요청 Header를 만든다."""
    headers = {
        "Authorization": f"Bearer {raw_key}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Mcp-Protocol-Version": "2026-07-28",
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    return headers


def test_mcp_http_requires_valid_bearer_key() -> None:
    """MCP Endpoint가 누락·변조된 Bearer Key를 401로 거부한다."""
    raw_key = "bmb_mcp_0123456789ab.test-secret"
    body = {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": _meta()}}
    with _client(raw_key) as client:
        missing = client.post("/mcp", json=body, headers=_headers("", "server/discover"))
        invalid = client.post("/mcp", json=body, headers=_headers(f"{raw_key}x", "server/discover"))

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_mcp_resource_metadata_advertises_read_and_write_scopes() -> None:
    """OAuth Client가 읽기·쓰기 Scope를 함께 요청하도록 지원 Scope를 모두 광고한다."""
    raw_key = "bmb_mcp_0123456789ab.test-secret"

    with _client(raw_key) as client:
        response = client.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == 200
    assert response.json()["resource"] == "http://testserver/mcp"
    assert response.json()["scopes_supported"] == ["wiki:read", "wiki:write"]


def test_mcp_http_discovers_and_calls_personal_wiki_search() -> None:
    """유효한 Key가 도구를 발견하고 Key 사용자 범위로 search를 호출한다."""
    raw_key = "bmb_mcp_0123456789ab.test-secret"
    discover = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "server/discover",
        "params": {"_meta": _meta()},
    }
    search = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "search",
            "arguments": {"query": "Obsidian"},
            "_meta": _meta(),
        },
    }
    with _client(raw_key) as client:
        discovered = client.post(
            "/mcp", json=discover, headers=_headers(raw_key, "server/discover")
        )
        searched = client.post(
            "/mcp", json=search, headers=_headers(raw_key, "tools/call", name="search")
        )

    assert discovered.status_code == 200
    assert "tools" in discovered.json()["result"]["capabilities"]
    assert searched.status_code == 200
    assert searched.json()["result"]["structuredContent"]["results"][0]["id"] == "document-1"


def test_mcp_http_calls_add_source_with_write_scope() -> None:
    """wiki:write Scope를 가진 Key가 add_source로 Source를 저장한다."""
    raw_key = "bmb_mcp_0123456789ab.test-secret"
    add_source = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "add_source",
            "arguments": {"title": "제목", "content": "본문"},
            "_meta": _meta(),
        },
    }
    with _client(raw_key, scopes=["wiki:read", "wiki:write"]) as client:
        response = client.post(
            "/mcp", json=add_source, headers=_headers(raw_key, "tools/call", name="add_source")
        )

    assert response.status_code == 200
    structured = response.json()["result"]["structuredContent"]
    assert structured["source_document_id"] == "source-1"


def test_mcp_http_rejects_add_source_without_write_scope() -> None:
    """wiki:read만 있는 Key는 add_source 호출이 거부된다."""
    raw_key = "bmb_mcp_0123456789ab.test-secret"
    add_source = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "add_source",
            "arguments": {"title": "제목", "content": "본문"},
            "_meta": _meta(),
        },
    }
    with _client(raw_key, scopes=["wiki:read"]) as client:
        response = client.post(
            "/mcp", json=add_source, headers=_headers(raw_key, "tools/call", name="add_source")
        )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result.get("isError") is True


def test_authenticated_user_id_enforces_required_scope(monkeypatch) -> None:
    """지정한 Scope가 없는 인증 Context는 Personal Wiki 사용자 ID를 내주지 않는다."""

    class _FakeAccessToken:
        subject = "42"
        scopes = ["wiki:write"]

    monkeypatch.setattr(mcp_main, "get_access_token", lambda: _FakeAccessToken())

    assert mcp_main._authenticated_user_id("wiki:write") == "42"
    try:
        mcp_main._authenticated_user_id("wiki:read")
        raised = False
    except PermissionError:
        raised = True
    assert raised


def test_run_uses_configured_mcp_port(monkeypatch) -> None:
    """전용 프로세스가 설정된 MCP 수신 포트로 서버를 기동한다."""
    lifecycle: list[str] = []
    run_options: dict[str, object] = {}

    class FakeContainer:
        async def startup(self) -> None:
            lifecycle.append("startup")

        async def shutdown(self) -> None:
            lifecycle.append("shutdown")

    class FakeServer:
        async def run_streamable_http_async(self, **options: object) -> None:
            run_options.update(options)

    settings = Settings(mcp_server_port=8101)
    container = FakeContainer()
    server = FakeServer()
    monkeypatch.setattr(mcp_main, "load_settings", lambda: settings)
    monkeypatch.setattr(mcp_main, "create_container", lambda _: container)
    monkeypatch.setattr(mcp_main, "build_mcp_server", lambda *_: server)

    asyncio.run(mcp_main._run())

    assert run_options["port"] == 8101
    assert lifecycle == ["startup", "shutdown"]


def test_main_handles_terminal_interrupt_without_traceback(monkeypatch) -> None:
    """전용 프로세스가 터미널 인터럽트를 정상 종료로 처리하는지 검증한다."""
    def interrupt(coroutine: object) -> None:
        """생성된 Coroutine을 닫고 터미널 인터럽트를 재현한다."""
        coroutine.close()  # type: ignore[attr-defined]
        raise KeyboardInterrupt

    monkeypatch.setattr(mcp_main.asyncio, "run", interrupt)

    mcp_main.main()
