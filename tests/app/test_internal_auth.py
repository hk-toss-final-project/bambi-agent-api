"""내부 API Bearer 인증과 공개 개발 화면의 경계를 검증한다."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import AppContainer, create_container
from app.main import create_app
from tests.conftest import TEST_AUTHORIZATION_HEADER, TEST_INTERNAL_TOKEN


def test_internal_service_route_rejects_missing_token(
    settings: Settings,
    container: AppContainer,
) -> None:
    """Service API 요청에 토큰이 없으면 표준 Bearer 401을 반환한다."""
    with TestClient(create_app(settings, container)) as client:
        response = client.put(
            "/internal/v1/users/user-1/context",
            json={"context_version": 1, "plan": "free"},
        )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_INTERNAL_TOKEN"
    assert response.headers["www-authenticate"] == "Bearer"


def test_internal_service_route_rejects_invalid_token(
    settings: Settings,
    container: AppContainer,
) -> None:
    """Service API 요청의 Bearer 토큰이 다르면 401을 반환한다."""
    with TestClient(create_app(settings, container)) as client:
        response = client.put(
            "/internal/v1/users/user-1/context",
            headers={"Authorization": "Bearer invalid-internal-token"},
            json={"context_version": 1, "plan": "free"},
        )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_INTERNAL_TOKEN"


def test_internal_service_route_accepts_configured_token(
    settings: Settings,
    container: AppContainer,
) -> None:
    """설정과 일치하는 Bearer 토큰은 기존 Service API 실행을 허용한다."""
    with TestClient(create_app(settings, container)) as client:
        response = client.put(
            "/internal/v1/users/user-1/context",
            headers=TEST_AUTHORIZATION_HEADER,
            json={"context_version": 1, "plan": "free"},
        )

    assert response.status_code == 200
    assert response.json()["feature_id"] == "SVC-001"


def test_internal_worker_route_requires_same_bearer_token(
    settings: Settings,
    container: AppContainer,
) -> None:
    """Service Worker 경로도 토큰 없는 요청을 실행 전에 차단한다."""
    with TestClient(create_app(settings, container)) as client:
        rejected = client.get("/internal/v1/publish-snapshots/missing")
        accepted = client.get(
            "/internal/v1/publish-snapshots/missing",
            headers=TEST_AUTHORIZATION_HEADER,
        )

    assert rejected.status_code == 401
    assert accepted.status_code == 404
    assert accepted.json()["code"] == "PUBLISH_SNAPSHOT_NOT_FOUND"


def test_internal_route_fails_closed_without_configured_secret() -> None:
    """서버에 Secret이 없으면 내부 API가 무인증으로 열리지 않는다."""
    settings = Settings(environment="test")
    container = create_container(settings)
    with TestClient(create_app(settings, container)) as client:
        response = client.get(
            "/internal/v1/jobs/job-1",
            headers={"Authorization": f"Bearer {TEST_INTERNAL_TOKEN}"},
        )

    assert response.status_code == 503
    assert response.json()["code"] == "INTERNAL_AUTH_NOT_CONFIGURED"


def test_openapi_declares_global_internal_bearer_scheme(client: TestClient) -> None:
    """Swagger가 내부 API에 재사용할 HTTP Bearer 보안 스키마를 제공한다."""
    schema = client.get("/openapi.json").json()
    security_scheme = schema["components"]["securitySchemes"]["InternalBearer"]

    assert security_scheme["type"] == "http"
    assert security_scheme["scheme"] == "bearer"
    assert security_scheme["bearerFormat"] == "opaque"
    assert schema["paths"]["/internal/v1/jobs/{job_id}"]["get"]["security"] == [
        {"InternalBearer": []}
    ]
    assert schema["paths"]["/internal/v1/jobs/statuses"]["post"]["security"] == [
        {"InternalBearer": []}
    ]
    assert "security" not in schema["paths"]["/system/live"]["get"]


def test_every_internal_openapi_operation_requires_bearer() -> None:
    """개발 API를 포함한 모든 내부 OpenAPI 작업에 Bearer 요구가 빠지지 않는다."""
    settings = Settings(
        environment="test",
        enable_dev_agent_api=True,
        internal_api_token=TEST_INTERNAL_TOKEN,
    )
    with TestClient(create_app(settings)) as client:
        schema = client.get("/openapi.json").json()

    internal_operations = [
        operation
        for path, path_item in schema["paths"].items()
        if path.startswith("/internal/v1/")
        for operation in path_item.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]

    assert internal_operations
    assert all(
        operation.get("security") == [{"InternalBearer": []}]
        for operation in internal_operations
    )


def test_development_pages_remain_public_without_bearer_token() -> None:
    """Swagger·Wiki Graph·개발 Graph 화면은 Bearer 토큰 없이 열린다."""
    settings = Settings(
        environment="test",
        enable_dev_agent_api=True,
        internal_api_token=TEST_INTERNAL_TOKEN,
    )
    with TestClient(create_app(settings)) as client:
        docs = client.get("/docs")
        wiki_graph = client.get("/wiki-graph")
        dev_graphs = client.get("/dev/graphs")

    assert docs.status_code == 200
    assert wiki_graph.status_code == 200
    assert dev_graphs.status_code == 200
    assert TEST_INTERNAL_TOKEN not in docs.text
    assert TEST_INTERNAL_TOKEN not in wiki_graph.text
    assert TEST_INTERNAL_TOKEN not in dev_graphs.text
