"""테스트 전반에서 재사용하는 결정적 공통 픽스처."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import AppContainer, create_container
from app.main import create_app
from app.services.mvp import AgentApiMvpService
from shared.contracts import FeatureRequest


@pytest.fixture
def feature_request() -> FeatureRequest:
    """외부 호출 없이 사용할 수 있는 공통 기능 요청을 반환한다."""
    return FeatureRequest(request_id="test-request", actor_id="test-service")


@pytest.fixture
def settings() -> Settings:
    """외부 연결 없이 실행할 수 있는 테스트 설정을 반환한다."""
    return Settings(
        app_name="Test Bambi Agent API",
        app_version="9.9.9",
        environment="test",
    )


@pytest.fixture
def container(settings: Settings) -> AppContainer:
    """각 테스트에서 독립적으로 사용할 애플리케이션 컨테이너를 반환한다."""
    return create_container(settings)


@pytest.fixture
def mvp_service(container: AppContainer) -> AgentApiMvpService:
    """테스트 컨테이너의 메모리 기반 MVP 서비스를 반환한다."""
    assert container.mvp_service is not None
    return container.mvp_service


@pytest.fixture
def client(settings: Settings, container: AppContainer) -> Iterator[TestClient]:
    """Lifespan이 활성화된 FastAPI 테스트 클라이언트를 제공한다."""
    with TestClient(create_app(settings, container)) as test_client:
        yield test_client
