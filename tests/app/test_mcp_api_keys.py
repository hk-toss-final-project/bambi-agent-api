"""Service API용 MCP API Key 관리 내부 엔드포인트를 검증한다."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import AppContainer
from app.main import create_app
from app.services.mcp_api_keys import McpApiKeyService
from tests.app.security.api_keys.test_lifecycle import _FakeApiKeyRepository
from tests.conftest import TEST_AUTHORIZATION_HEADER, TEST_INTERNAL_TOKEN


def _client() -> TestClient:
    """가짜 API Key 저장소가 연결된 내부 API Client를 만든다."""
    settings = Settings(environment="test", internal_api_token=TEST_INTERNAL_TOKEN)
    container = AppContainer(
        settings=settings,
        mcp_api_key_service=McpApiKeyService(_FakeApiKeyRepository()),
    )
    client = TestClient(create_app(settings, container))
    client.headers.update(TEST_AUTHORIZATION_HEADER)
    return client


def test_mcp_api_key_create_list_and_revoke_routes() -> None:
    """원문 1회 발급 후 목록에서 숨기고 폐기 상태를 반환한다."""
    with _client() as client:
        created = client.post(
            "/internal/v1/users/42/mcp-api-keys",
            json={"name": "Claude Desktop"},
        )
        listed = client.get("/internal/v1/users/42/mcp-api-keys")
        revoked = client.delete(
            "/internal/v1/users/42/mcp-api-keys/11111111-1111-1111-1111-111111111111"
        )

    assert created.status_code == 201
    assert created.json()["id"] == "11111111-1111-1111-1111-111111111111"
    assert created.json()["api_key"].startswith("bmb_mcp_")
    assert created.json()["token_type"] == "Bearer"
    assert listed.status_code == 200
    assert "api_key" not in listed.json()["items"][0]
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"


def test_mcp_api_key_rejects_blank_name_and_past_expiration() -> None:
    """공백 이름과 과거 만료 시각을 요청 검증 단계에서 거부한다."""
    with _client() as client:
        blank = client.post(
            "/internal/v1/users/42/mcp-api-keys",
            json={"name": "   "},
        )
        expired = client.post(
            "/internal/v1/users/42/mcp-api-keys",
            json={"name": "Old", "expires_at": datetime(2020, 1, 1, tzinfo=UTC).isoformat()},
        )

    assert blank.status_code == 422
    assert expired.status_code == 422
