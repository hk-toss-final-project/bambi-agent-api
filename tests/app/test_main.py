"""FastAPI 애플리케이션 팩토리의 기본 조립 결과를 검증한다."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


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
        "svc_008",
        "svc_013",
        "svc_014",
        "sw_004",
        "sw_009",
    } <= operation_ids
