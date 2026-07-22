"""시스템 상태와 버전 FastAPI 엔드포인트를 검증한다."""

from fastapi.testclient import TestClient

from app.dependencies import AppContainer


def test_liveness_and_readiness(client: TestClient) -> None:
    """실행 중인 앱이 생존 및 준비 상태를 반환하는지 검증한다."""
    live_response = client.get("/system/live")
    ready_response = client.get("/system/ready")

    assert live_response.status_code == 200
    assert live_response.json() == {"status": "ok", "checks": {}}
    assert ready_response.status_code == 200
    assert ready_response.json()["status"] == "ready"
    assert all(ready_response.json()["checks"].values())


def test_readiness_fails_before_container_startup(container: AppContainer) -> None:
    """Lifespan 시작 전 컨테이너가 준비되지 않은 상태인지 검증한다."""
    assert container.ready is False


def test_version_uses_application_settings(client: TestClient) -> None:
    """Version API가 앱 이름, 버전과 환경을 반환하는지 검증한다."""
    response = client.get("/system/version")

    assert response.status_code == 200
    assert response.json() == {
        "name": "Test Report Builder Agent API",
        "version": "9.9.9",
        "environment": "test",
    }
