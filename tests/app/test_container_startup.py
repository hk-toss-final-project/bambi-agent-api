"""DB 연결 실패 시 컨테이너 기동 동작 검증.

이 프로세스는 API와 키워드 비서 웹 UI를 함께 제공한다. 비서는 PostgreSQL이
필요 없으므로, DB 연결 실패가 앱 기동 자체를 막아서는 안 된다.
"""

import asyncio

import pytest

from app.config import Settings
from app.dependencies import AppContainer


class _FailingRepository:
    """startup에서 항상 실패하는 저장소 더미."""

    def __init__(self) -> None:
        self.shutdown_called = False

    async def startup(self) -> None:
        """연결 실패를 재현한다."""
        raise TimeoutError("pool initialization incomplete")

    async def shutdown(self) -> None:
        """실패한 Pool 정리 호출을 기록한다."""
        self.shutdown_called = True


class _WorkingRepository:
    """정상 동작하는 저장소 더미."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def startup(self) -> None:
        """정상 연결을 재현한다."""
        self.started = True

    async def shutdown(self) -> None:
        """정상 종료를 기록한다."""
        self.stopped = True


def _container(**kwargs) -> AppContainer:
    """테스트용 컨테이너를 만든다."""
    return AppContainer(settings=Settings(), **kwargs)


def test_startup_survives_database_failure() -> None:
    """DB 연결이 실패해도 컨테이너는 준비 완료 상태가 된다.

    실패가 기동을 막으면 DB가 필요 없는 키워드 비서 UI까지 못 뜬다.
    """
    repository = _FailingRepository()
    container = _container(database=repository)  # type: ignore[arg-type]

    asyncio.run(container.startup())

    assert container.ready is True
    assert container.database_error is not None
    assert "TimeoutError" in container.database_error


def test_startup_failure_disables_database_services() -> None:
    """DB 연결 실패 시 DB 기반 서비스를 내려 503으로 응답하게 만든다.

    조용히 인메모리로 대체하지 않는다 — 실제 장애를 정상 동작처럼 보이게
    하지 않기 위해서다.
    """
    container = _container(
        database=_FailingRepository(),  # type: ignore[arg-type]
        mvp_service=object(),  # type: ignore[arg-type]
        publish_snapshot_service=object(),  # type: ignore[arg-type]
        wiki_graph_service=object(),  # type: ignore[arg-type]
        generated_content_service=object(),  # type: ignore[arg-type]
    )

    asyncio.run(container.startup())

    assert container.database is None
    assert container.mvp_service is None
    assert container.publish_snapshot_service is None
    assert container.wiki_graph_service is None
    assert container.generated_content_service is None


def test_startup_failure_cleans_up_started_repositories() -> None:
    """앞선 저장소가 이미 열렸다면 실패 시 함께 정리한다."""
    working = _WorkingRepository()
    failing = _FailingRepository()
    container = _container(
        database=working,  # type: ignore[arg-type]
        wiki_graph_repository=failing,  # type: ignore[arg-type]
    )

    asyncio.run(container.startup())

    assert working.started is True
    assert working.stopped is True      # 정리됨
    assert failing.shutdown_called is True


def test_startup_keeps_services_when_database_works() -> None:
    """DB가 정상이면 서비스를 그대로 유지한다 (회귀 방지)."""
    service = object()
    container = _container(
        database=_WorkingRepository(),  # type: ignore[arg-type]
        mvp_service=service,  # type: ignore[arg-type]
    )

    asyncio.run(container.startup())

    assert container.ready is True
    assert container.database_error is None
    assert container.mvp_service is service


def test_shutdown_after_failed_startup_is_safe() -> None:
    """기동 실패 후 종료해도 예외가 나지 않는다."""
    container = _container(database=_FailingRepository())  # type: ignore[arg-type]

    asyncio.run(container.startup())
    asyncio.run(container.shutdown())  # 예외 없이 끝나야 한다

    assert container.ready is False


def test_app_serves_assistant_ui_without_database(monkeypatch) -> None:
    """DB가 없어도 앱이 기동하고 비서 UI를 제공한다 (통합 확인)."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = Settings(agent_database_url=None, docs_enabled=True)
    application = create_app(settings=settings)

    with TestClient(application) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'action="/search"' in response.text
