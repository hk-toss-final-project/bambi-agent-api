"""FastAPI 애플리케이션 팩토리의 기본 조립 결과를 검증한다."""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
from uvicorn.config import Config

from app.config import Settings
from app.main import create_app, selector_event_loop


def test_selector_event_loop_is_psycopg_compatible() -> None:
    """psycopg 비동기 연결이 요구하는 Selector 루프를 만드는지 검증한다."""
    loop = selector_event_loop()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()


def test_uvicorn_resolves_the_loop_factory_from_import_string() -> None:
    """uvicorn --loop 옵션이 이 팩토리를 그대로 찾아 쓰는지 검증한다.

    실행 설정과 문서가 `--loop app.main:selector_event_loop`를 지정하므로,
    uvicorn이 커스텀 팩토리를 해석하는 경로가 깨지면 서버가 Windows에서 다시
    ProactorEventLoop로 떠 DB Pool이 실패한다.
    """
    config = Config("app.main:app", loop="app.main:selector_event_loop")

    assert config.get_loop_factory() is selector_event_loop


def test_create_app_uses_settings_metadata() -> None:
    """앱 팩토리가 전달된 이름과 버전을 FastAPI Metadata에 반영하는지 검증한다."""
    application = create_app(Settings(app_name="Test Agent API", app_version="9.9.9"))

    assert isinstance(application, FastAPI)
    assert application.title == "Test Agent API"
    assert application.version == "9.9.9"


def test_create_app_can_disable_openapi_documents() -> None:
    """운영 설정에서 OpenAPI 문서 경로를 비활성화할 수 있는지 검증한다."""
    application = create_app(Settings(docs_enabled=False))

    assert application.docs_url is None
    assert application.redoc_url is None
    assert application.openapi_url is None


def test_agent_api_does_not_mount_public_mcp_endpoint(client: TestClient) -> None:
    """내부 Agent API 프로세스가 외부 MCP 경로를 함께 노출하지 않는지 검증한다."""
    response = client.post("/mcp")

    assert response.status_code == 404


def test_swagger_ui_is_available(client: TestClient) -> None:
    """Swagger UI가 활성화된 문서 경로에서 OpenAPI Schema를 참조하는지 검증한다."""
    response = client.get("/docs")

    assert response.status_code == 200
    assert "Swagger UI" in response.text
    assert "url: '/openapi.json'" in response.text


def test_swagger_ui_contains_theme_toggle(client: TestClient) -> None:
    """Swagger UI가 다크·라이트 모드 전환과 선택 상태 저장 기능을 제공하는지 검증한다."""
    response = client.get("/docs")

    assert response.status_code == 200
    assert 'id = "swagger-theme-toggle"' in response.text
    assert 'html[data-theme="dark"]' in response.text
    assert 'storageKey = "report-builder-swagger-theme"' in response.text
    assert "prefers-color-scheme: dark" in response.text
    assert 'classList.toggle("dark-mode", initialTheme === "dark")' in response.text
    assert 'classList.toggle("dark-mode", theme === "dark")' in response.text
    assert "다크 모드로 전환" in response.text
    assert "라이트 모드로 전환" in response.text


def test_swagger_ui_persists_global_authorization(client: TestClient) -> None:
    """Swagger에 한 번 입력한 Bearer 토큰을 새로고침 후에도 유지한다."""
    response = client.get("/docs")

    assert response.status_code == 200
    assert '"persistAuthorization": true' in response.text


def test_openapi_contains_swagger_metadata(client: TestClient) -> None:
    """OpenAPI Schema에 API 설명과 영역별 태그 설명이 포함되는지 검증한다."""
    response = client.get("/openapi.json")
    schema = response.json()

    assert response.status_code == 200
    assert "LangGraph" in schema["info"]["description"]
    assert {tag["name"] for tag in schema["tags"]} == {
        "system",
        "service-api",
        "service-worker",
    }
    assert schema["paths"]["/system/live"]["get"]["summary"] == (
        "프로세스 생존 상태 조회"
    )


def test_openapi_contains_fastapi_mvp_operations(client: TestClient) -> None:
    """OpenAPI 문서에 설계된 FastAPI MVP 기능 ID가 등록되는지 검증한다."""
    response = client.get("/openapi.json")
    operation_ids = {
        operation["operationId"]
        for path_item in response.json()["paths"].values()
        for operation in path_item.values()
        if isinstance(operation, dict) and "operationId" in operation
    }

    assert response.status_code == 200
    assert {
        "sys_009",
        "sys_010",
        "sys_011",
        "svc_001",
        "svc_002",
        "svc_003",
        "svc_004",
        "svc_006",
        "svc_008",
        "svc_013",
        "svc_014",
        "pwiki_003",
        "pwiki_013",
        "int_001_get",
        "int_011_rebuild",
        "wba_015_delete",
        "sw_004",
        "sw_004_batch_claim",
        "sw_009",
        "sw_009_batch_ack",
    } <= operation_ids


def test_openapi_contains_publish_batch_examples(client: TestClient) -> None:
    """Swagger가 Batch Claim과 ACK 요청 예시를 제공하는지 검증한다."""
    schema = client.get("/openapi.json").json()
    claim_schema = schema["components"]["schemas"]["PublishBatchClaimRequest"]
    ack_schema = schema["components"]["schemas"]["PublishBatchAckRequest"]

    assert claim_schema["examples"][0]["worker_id"] == "service-worker-01"
    assert claim_schema["examples"][0]["limit"] == 50
    assert ack_schema["examples"][0]["items"][0]["status"] == "published"
