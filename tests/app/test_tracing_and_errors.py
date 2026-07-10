"""요청 추적 미들웨어와 공통 오류 응답을 검증한다."""

from fastapi.testclient import TestClient


def test_tracing_headers_are_generated(client: TestClient) -> None:
    """추적 헤더가 없는 요청에 Request ID와 Trace ID가 생성되는지 검증한다."""
    response = client.get("/system/live")

    assert response.status_code == 200
    assert len(response.headers["X-Request-ID"]) == 32
    assert len(response.headers["X-Trace-ID"]) == 32


def test_valid_tracing_headers_are_preserved(client: TestClient) -> None:
    """호출자가 전달한 유효한 추적 ID가 응답까지 유지되는지 검증한다."""
    response = client.get(
        "/system/live",
        headers={"X-Request-ID": "request-123", "X-Trace-ID": "trace-456"},
    )

    assert response.headers["X-Request-ID"] == "request-123"
    assert response.headers["X-Trace-ID"] == "trace-456"


def test_validation_error_uses_common_schema(client: TestClient) -> None:
    """잘못된 내부 API 요청이 공통 검증 오류 형식으로 반환되는지 검증한다."""
    response = client.post(
        "/internal/v1/users/user-1/wiki-sources/urls",
        json={"source_event_id": "event-1", "url": "not-a-url"},
        headers={"X-Request-ID": "validation-request"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_VALIDATION_ERROR"
    assert response.json()["request_id"] == "validation-request"
    assert response.json()["details"]
