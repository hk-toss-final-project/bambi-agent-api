"""FastAPI 라우터에서 사용하는 애플리케이션 의존성 컨테이너."""

from dataclasses import dataclass

from fastapi import Depends, Request, status

from app.config import Settings
from app.exceptions import AgentApiError, ErrorDetail
from app.services.mvp import AgentApiMvpService
from app.services.wiki_graph import WikiGraphService
from infrastructure.persistence.postgres_publish_snapshots import (
    PostgresPublishSnapshotRepository,
)
from infrastructure.persistence.postgres_wiki_graph import (
    PostgresWikiGraphRepository,
)


@dataclass(slots=True)
class AppContainer:
    """API 요청 처리에 필요한 애플리케이션 컴포넌트 모음."""

    settings: Settings
    database: PostgresPublishSnapshotRepository | None = None
    wiki_graph_repository: PostgresWikiGraphRepository | None = None
    vector_store: object | None = None
    queue: object | None = None
    event_bus: object | None = None
    llm_provider: object | None = None
    embedding_provider: object | None = None
    mvp_service: AgentApiMvpService | None = None
    wiki_graph_service: WikiGraphService | None = None
    ready: bool = False

    async def startup(self) -> None:
        """요청을 받을 수 있도록 컨테이너 상태를 준비 완료로 변경한다."""
        if self.database is not None:
            await self.database.startup()
        if self.wiki_graph_repository is not None:
            await self.wiki_graph_repository.startup()
        self.mvp_service = self.mvp_service or AgentApiMvpService()
        self.ready = True

    async def shutdown(self) -> None:
        """새 요청 처리를 중단하고 PostgreSQL 연결 Pool을 종료한다."""
        self.ready = False
        if self.database is not None:
            await self.database.shutdown()
        if self.wiki_graph_repository is not None:
            await self.wiki_graph_repository.shutdown()


def create_container(settings: Settings) -> AppContainer:
    """설정으로부터 기본 MVP 애플리케이션 컨테이너를 생성한다."""
    if settings.agent_database_url:
        database = PostgresPublishSnapshotRepository(settings.agent_database_url)
        wiki_graph_repository = PostgresWikiGraphRepository(
            settings.agent_database_url
        )
        return AppContainer(
            settings=settings,
            database=database,
            wiki_graph_repository=wiki_graph_repository,
            mvp_service=AgentApiMvpService(database),
            wiki_graph_service=WikiGraphService(wiki_graph_repository),
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


def get_wiki_graph_service(
    container: AppContainer = Depends(get_container),
) -> WikiGraphService:
    """PostgreSQL 개인 Wiki Graph 조회 서비스를 반환한다."""
    if container.wiki_graph_service is None:
        raise AgentApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorDetail(
                code="SERVICE_NOT_READY",
                message="개인 Wiki Graph 저장소가 준비되지 않았습니다.",
                retryable=True,
            ),
        )
    return container.wiki_graph_service
