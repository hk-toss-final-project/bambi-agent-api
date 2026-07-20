"""FastAPI 라우터에서 사용하는 애플리케이션 의존성 컨테이너."""

from dataclasses import dataclass

from fastapi import Depends, Request, status

from app.config import Settings
from app.exceptions import AgentApiError, ErrorDetail
from app.services.mvp import AgentApiMvpService
from app.services.publish_snapshots import (
    InMemoryPublishSnapshotRepository,
    PublishSnapshotService,
)
from app.services.agent_workflows import AgentWorkflowService
from app.services.interests import InterestService
from app.services.generated_content import GeneratedContentService
from app.services.development_scenarios import DevelopmentScenarioService
from app.services.latest_information import LatestInformationService
from app.services.wiki_graph import WikiGraphService
from app.services.wiki_documents import WikiDocumentService
from infrastructure.persistence.postgres_publish_snapshots import (
    PostgresPublishSnapshotRepository,
)
from infrastructure.persistence.postgres_wiki_graph import (
    PostgresWikiGraphRepository,
)
from infrastructure.persistence.postgres_agent_jobs import PostgresAgentJobRepository


@dataclass(slots=True)
class AppContainer:
    """API 요청 처리에 필요한 애플리케이션 컴포넌트 모음."""

    settings: Settings
    database: PostgresPublishSnapshotRepository | None = None
    wiki_graph_repository: PostgresWikiGraphRepository | None = None
    agent_job_repository: PostgresAgentJobRepository | None = None
    vector_store: object | None = None
    queue: object | None = None
    event_bus: object | None = None
    llm_provider: object | None = None
    embedding_provider: object | None = None
    mvp_service: AgentApiMvpService | None = None
    publish_snapshot_service: PublishSnapshotService | None = None
    wiki_graph_service: WikiGraphService | None = None
    wiki_document_service: WikiDocumentService | None = None
    agent_workflow_service: AgentWorkflowService | None = None
    interest_service: InterestService | None = None
    latest_information_service: LatestInformationService | None = None
    generated_content_service: GeneratedContentService | None = None
    development_scenario_service: DevelopmentScenarioService | None = None
    ready: bool = False

    async def startup(self) -> None:
        """요청을 받을 수 있도록 컨테이너 상태를 준비 완료로 변경한다."""
        if self.database is not None:
            await self.database.startup()
        if self.wiki_graph_repository is not None:
            await self.wiki_graph_repository.startup()
        if self.agent_job_repository is not None:
            await self.agent_job_repository.startup()
        self.ready = True

    async def shutdown(self) -> None:
        """새 요청 처리를 중단하고 PostgreSQL 연결 Pool을 종료한다."""
        self.ready = False
        if self.database is not None:
            await self.database.shutdown()
        if self.wiki_graph_repository is not None:
            await self.wiki_graph_repository.shutdown()
        if self.agent_job_repository is not None:
            await self.agent_job_repository.shutdown()


def create_container(settings: Settings) -> AppContainer:
    """설정으로부터 기본 MVP 애플리케이션 컨테이너를 생성한다."""
    if settings.agent_database_url:
        database = PostgresPublishSnapshotRepository(settings.agent_database_url)
        wiki_graph_repository = PostgresWikiGraphRepository(
            settings.agent_database_url
        )
        agent_job_repository = PostgresAgentJobRepository(settings.agent_database_url)
        interest_service = InterestService(wiki_graph_repository)
        mvp_service = AgentApiMvpService(agent_job_repository)
        publish_snapshot_service = PublishSnapshotService(database)
        workflow_service = AgentWorkflowService(agent_job_repository, settings)
        latest_information_service = LatestInformationService(
            wiki_graph_repository,
            interest_service,
            settings,
        )
        return AppContainer(
            settings=settings,
            database=database,
            wiki_graph_repository=wiki_graph_repository,
            agent_job_repository=agent_job_repository,
            mvp_service=mvp_service,
            publish_snapshot_service=publish_snapshot_service,
            wiki_graph_service=WikiGraphService(wiki_graph_repository),
            wiki_document_service=WikiDocumentService(wiki_graph_repository),
            agent_workflow_service=workflow_service,
            interest_service=interest_service,
            latest_information_service=latest_information_service,
            generated_content_service=GeneratedContentService(agent_job_repository),
            development_scenario_service=DevelopmentScenarioService(
                mvp_service,
                workflow_service,
                interest_service,
                latest_information_service,
            ),
        )
    return AppContainer(
        settings=settings,
        publish_snapshot_service=PublishSnapshotService(
            InMemoryPublishSnapshotRepository()
        ),
    )


def get_container(request: Request) -> AppContainer:
    """현재 FastAPI 애플리케이션에 연결된 컨테이너를 반환한다."""
    return request.app.state.container


def get_mvp_service(
    container: AppContainer = Depends(get_container),
) -> AgentApiMvpService:
    """MVP API 요청 처리에 사용할 애플리케이션 서비스를 반환한다."""
    if container.mvp_service is None:
        raise AgentApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorDetail(
                code="SERVICE_NOT_READY",
                message="사용자 원본·Job 저장소가 준비되지 않았습니다.",
                retryable=True,
            ),
        )
    return container.mvp_service


def get_publish_snapshot_service(
    container: AppContainer = Depends(get_container),
) -> PublishSnapshotService:
    """발행 Snapshot 조회·Claim·ACK 서비스를 반환한다."""
    if container.publish_snapshot_service is None:
        raise AgentApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorDetail(
                code="SERVICE_NOT_READY",
                message="발행 Snapshot 저장소가 준비되지 않았습니다.",
                retryable=True,
            ),
        )
    return container.publish_snapshot_service


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


def get_agent_workflow_service(
    container: AppContainer = Depends(get_container),
) -> AgentWorkflowService:
    """개발용 동기 Agent Job 실행 서비스를 반환한다."""
    if container.agent_workflow_service is None:
        raise AgentApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorDetail(
                code="SERVICE_NOT_READY",
                message="Agent Job 저장소가 준비되지 않았습니다.",
                retryable=True,
            ),
        )
    return container.agent_workflow_service


def get_wiki_document_service(
    container: AppContainer = Depends(get_container),
) -> WikiDocumentService:
    """개인 Wiki 문서·Build 조회 서비스를 반환한다."""
    if container.wiki_document_service is None:
        raise AgentApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorDetail(
                code="SERVICE_NOT_READY",
                message="개인 Wiki 문서 저장소가 준비되지 않았습니다.",
                retryable=True,
            ),
        )
    return container.wiki_document_service


def get_interest_service(
    container: AppContainer = Depends(get_container),
) -> InterestService:
    """개인 Wiki 기반 관심 키워드 계산·조회 서비스를 반환한다."""
    if container.interest_service is None:
        raise AgentApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorDetail(
                code="SERVICE_NOT_READY",
                message="관심 Profile 저장소가 준비되지 않았습니다.",
                retryable=True,
            ),
        )
    return container.interest_service


def get_latest_information_service(
    container: AppContainer = Depends(get_container),
) -> LatestInformationService:
    """외부 최신 정보 수집·Global 저장 서비스를 반환한다."""
    if container.latest_information_service is None:
        raise AgentApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorDetail(
                code="SERVICE_NOT_READY",
                message="최신 정보 저장소가 준비되지 않았습니다.",
                retryable=True,
            ),
        )
    return container.latest_information_service


def get_generated_content_service(
    container: AppContainer = Depends(get_container),
) -> GeneratedContentService:
    """Bambi 생성 콘텐츠 후보 목록·상세 조회 서비스를 반환한다."""
    if container.generated_content_service is None:
        raise AgentApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorDetail(
                code="SERVICE_NOT_READY",
                message="생성 콘텐츠 저장소가 준비되지 않았습니다.",
                retryable=True,
            ),
        )
    return container.generated_content_service


def get_development_scenario_service(
    container: AppContainer = Depends(get_container),
) -> DevelopmentScenarioService:
    """원본에서 Bambi 콘텐츠까지 실행하는 개발 시나리오 서비스를 반환한다."""
    if container.development_scenario_service is None:
        raise AgentApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorDetail(
                code="SERVICE_NOT_READY",
                message="개발 시나리오 실행 서비스가 준비되지 않았습니다.",
                retryable=True,
            ),
        )
    return container.development_scenario_service
