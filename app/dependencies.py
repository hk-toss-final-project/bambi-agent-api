"""FastAPI 라우터에서 사용하는 애플리케이션 의존성 컨테이너."""

from dataclasses import dataclass

from fastapi import Depends, Request

from app.config import Settings
from app.services.mvp import AgentApiMvpService
from infrastructure.persistence.postgres_publish_snapshots import (
    PostgresPublishSnapshotRepository,
)


@dataclass(slots=True)
class AppContainer:
    """API 요청 처리에 필요한 애플리케이션 컴포넌트 모음."""

    settings: Settings
    database: PostgresPublishSnapshotRepository | None = None
    vector_store: object | None = None
    queue: object | None = None
    event_bus: object | None = None
    llm_provider: object | None = None
    embedding_provider: object | None = None
    mvp_service: AgentApiMvpService | None = None
    ready: bool = False

    async def startup(self) -> None:
        """요청을 받을 수 있도록 컨테이너 상태를 준비 완료로 변경한다."""
        if self.database is not None:
            await self.database.startup()
        self.mvp_service = self.mvp_service or AgentApiMvpService()
        self.ready = True

    async def shutdown(self) -> None:
        """새 요청 처리를 중단하고 PostgreSQL 연결 Pool을 종료한다."""
        self.ready = False
        if self.database is not None:
            await self.database.shutdown()


def create_container(settings: Settings) -> AppContainer:
    """설정으로부터 기본 MVP 애플리케이션 컨테이너를 생성한다."""
    if settings.agent_database_url:
        database = PostgresPublishSnapshotRepository(settings.agent_database_url)
        return AppContainer(
            settings=settings,
            database=database,
            mvp_service=AgentApiMvpService(database),
        )
    return AppContainer(settings=settings, mvp_service=AgentApiMvpService())


def get_container(request: Request) -> AppContainer:
    """현재 FastAPI 애플리케이션에 연결된 컨테이너를 반환한다."""
    return request.app.state.container


def get_mvp_service(
    container: AppContainer = Depends(get_container),
) -> AgentApiMvpService:
    """MVP API 요청 처리에 사용할 애플리케이션 서비스를 반환한다."""
    if container.mvp_service is None:
        raise RuntimeError("MVP 서비스가 초기화되지 않았습니다.")
    return container.mvp_service
