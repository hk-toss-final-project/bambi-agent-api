"""FastAPI 라우터에서 사용하는 애플리케이션 의존성 컨테이너."""

import logging
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
from app.services.collection_schedules import CollectionScheduleService
from app.services.interests import InterestService
from app.services.generated_content import GeneratedContentService
from app.services.development_scenarios import DevelopmentScenarioService
from app.services.latest_information import LatestInformationService
from app.services.mcp_api_keys import McpApiKeyService
from app.services.briefing_topics import BriefingTopicsService
from app.services.wiki_graph import WikiGraphService
from app.services.wiki_navigator import WikiNavigatorService
from app.services.wiki_documents import WikiDocumentService
from infrastructure.persistence.postgres_publish_snapshots import (
    PostgresPublishSnapshotRepository,
)
from infrastructure.persistence.postgres_wiki_graph import (
    PostgresWikiGraphRepository,
)
from infrastructure.persistence.postgres_agent_jobs import PostgresAgentJobRepository
from infrastructure.persistence.postgres_api_keys import PostgresApiKeyRepository
from workers.api import worker_001

logger = logging.getLogger("app.dependencies")


@dataclass(slots=True)
class AppContainer:
    """API 요청 처리에 필요한 애플리케이션 컴포넌트 모음."""

    settings: Settings
    database: PostgresPublishSnapshotRepository | None = None
    wiki_graph_repository: PostgresWikiGraphRepository | None = None
    agent_job_repository: PostgresAgentJobRepository | None = None
    mcp_api_key_repository: PostgresApiKeyRepository | None = None
    vector_store: object | None = None
    queue: object | None = None
    event_bus: object | None = None
    llm_provider: object | None = None
    embedding_provider: object | None = None
    mvp_service: AgentApiMvpService | None = None
    publish_snapshot_service: PublishSnapshotService | None = None
    wiki_graph_service: WikiGraphService | None = None
    briefing_topics_service: BriefingTopicsService | None = None
    wiki_navigator_service: WikiNavigatorService | None = None
    wiki_document_service: WikiDocumentService | None = None
    agent_workflow_service: AgentWorkflowService | None = None
    interest_service: InterestService | None = None
    latest_information_service: LatestInformationService | None = None
    generated_content_service: GeneratedContentService | None = None
    development_scenario_service: DevelopmentScenarioService | None = None
    collection_schedule_service: CollectionScheduleService | None = None
    mcp_api_key_service: McpApiKeyService | None = None
    ready: bool = False
    database_error: str | None = None

    async def startup(self) -> None:
        """저장소 연결을 열고 요청을 받을 수 있는 상태로 만든다.

        PostgreSQL 연결에 실패해도 앱 기동은 막지 않는다. 이 프로세스는 API와
        함께 키워드 비서 웹 UI도 제공하는데, 비서는 DB가 필요 없기 때문이다.
        (서버를 하나로 합치기 전에는 비서를 DB 없이 띄울 수 있었고, 그 성질을
        유지한다.)

        연결에 실패하면 DB 기반 서비스를 모두 내려 둔다. 해당 API는 503
        SERVICE_NOT_READY로 명확히 실패하며, 조용히 인메모리로 대체하지 않는다
        (실제 장애를 정상 동작처럼 보이게 만들지 않기 위해서다).
        """
        repositories = (
            self.database,
            self.wiki_graph_repository,
            self.agent_job_repository,
            self.mcp_api_key_repository,
        )
        try:
            for repository in repositories:
                if repository is not None:
                    await repository.startup()
        except Exception as error:
            self.database_error = f"{type(error).__name__}: {error}"
            logger.warning(
                "PostgreSQL 연결에 실패해 DB 기반 API를 비활성화합니다 "
                "(키워드 비서 UI 등 DB가 필요 없는 경로는 그대로 동작합니다): %s",
                self.database_error,
            )
            await self._disable_database_services()
        self.ready = True

    async def _disable_database_services(self) -> None:
        """DB 연결 실패 시 저장소·서비스를 내려 503으로 응답하게 만든다."""
        for repository in (
            self.database,
            self.wiki_graph_repository,
            self.agent_job_repository,
            self.mcp_api_key_repository,
        ):
            if repository is None:
                continue
            try:
                await repository.shutdown()
            except Exception:  # 이미 실패한 Pool 정리 중 오류는 무시한다.
                logger.debug("실패한 저장소 Pool 정리 중 오류를 무시합니다.", exc_info=True)
        self.database = None
        self.wiki_graph_repository = None
        self.agent_job_repository = None
        self.mvp_service = None
        self.publish_snapshot_service = None
        self.wiki_graph_service = None
        self.briefing_topics_service = None
        self.wiki_navigator_service = None
        self.wiki_document_service = None
        self.agent_workflow_service = None
        self.interest_service = None
        self.latest_information_service = None
        self.generated_content_service = None
        self.development_scenario_service = None
        self.collection_schedule_service = None
        self.mcp_api_key_service = None

    async def shutdown(self) -> None:
        """새 요청 처리를 중단하고 PostgreSQL 연결 Pool을 종료한다."""
        self.ready = False
        if self.database is not None:
            await self.database.shutdown()
        if self.wiki_graph_repository is not None:
            await self.wiki_graph_repository.shutdown()
        if self.agent_job_repository is not None:
            await self.agent_job_repository.shutdown()
        if self.mcp_api_key_repository is not None:
            await self.mcp_api_key_repository.shutdown()


def create_container(settings: Settings) -> AppContainer:
    """설정으로부터 기본 MVP 애플리케이션 컨테이너를 생성한다."""
    if settings.agent_database_url:
        database = PostgresPublishSnapshotRepository(settings.agent_database_url)
        wiki_graph_repository = PostgresWikiGraphRepository(
            settings.agent_database_url
        )
        agent_job_repository = PostgresAgentJobRepository(
            settings.agent_database_url,
            wiki_build_quiet_minutes=settings.wiki_build_quiet_minutes,
            wiki_build_max_wait_minutes=settings.wiki_build_max_wait_minutes,
            wiki_read_pipeline_version=settings.wiki_read_pipeline_version,
            wiki_maintenance_pipeline_version=(
                settings.wiki_maintenance_pipeline_version
            ),
        )
        mcp_api_key_repository = PostgresApiKeyRepository(settings.agent_database_url)
        interest_service = InterestService(wiki_graph_repository)
        mvp_service = AgentApiMvpService(agent_job_repository)
        publish_snapshot_service = PublishSnapshotService(database)
        workflow_service = AgentWorkflowService(agent_job_repository, settings)
        latest_information_service = LatestInformationService(
            wiki_graph_repository,
            interest_service,
            settings,
            news_collector=worker_001,
        )
        return AppContainer(
            settings=settings,
            database=database,
            wiki_graph_repository=wiki_graph_repository,
            agent_job_repository=agent_job_repository,
            mcp_api_key_repository=mcp_api_key_repository,
            mvp_service=mvp_service,
            publish_snapshot_service=publish_snapshot_service,
            wiki_graph_service=WikiGraphService(wiki_graph_repository),
            briefing_topics_service=BriefingTopicsService(wiki_graph_repository),
            wiki_navigator_service=WikiNavigatorService(wiki_graph_repository),
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
            collection_schedule_service=CollectionScheduleService(
                agent_job_repository, settings
            ),
            mcp_api_key_service=McpApiKeyService(mcp_api_key_repository),
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


def get_wiki_navigator_service(
    container: AppContainer = Depends(get_container),
) -> WikiNavigatorService:
    """개인 Wiki Navigator Read 서비스를 반환한다."""
    if container.wiki_navigator_service is None:
        raise AgentApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorDetail(
                code="SERVICE_NOT_READY",
                message="개인 Wiki Navigator 저장소가 준비되지 않았습니다.",
                retryable=True,
            ),
        )
    return container.wiki_navigator_service


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
    """Report Builder 생성 콘텐츠 후보 목록·상세 조회 서비스를 반환한다."""
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


def get_collection_schedule_service(
    container: AppContainer = Depends(get_container),
) -> CollectionScheduleService:
    """Service가 정기 수집 주기를 조정하는 스케줄 관리 서비스를 반환한다."""
    if container.collection_schedule_service is None:
        raise AgentApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorDetail(
                code="SERVICE_NOT_READY",
                message="수집 스케줄 저장소가 준비되지 않았습니다.",
                retryable=True,
            ),
        )
    return container.collection_schedule_service


def get_development_scenario_service(
    container: AppContainer = Depends(get_container),
) -> DevelopmentScenarioService:
    """원본에서 Report Builder 콘텐츠까지 실행하는 개발 시나리오 서비스를 반환한다."""
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


def get_mcp_api_key_service(
    container: AppContainer = Depends(get_container),
) -> McpApiKeyService:
    """MCP API Key 발급·조회·폐기 서비스를 반환한다."""
    if container.mcp_api_key_service is None:
        raise AgentApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorDetail(
                code="SERVICE_NOT_READY",
                message="MCP API Key 저장소가 준비되지 않았습니다.",
                retryable=True,
            ),
        )
    return container.mcp_api_key_service


def get_briefing_topics_service(
    container: AppContainer = Depends(get_container),
) -> BriefingTopicsService:
    """아침 브리핑 주제 선정 서비스를 반환한다."""
    if container.briefing_topics_service is None:
        raise AgentApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorDetail(
                code="SERVICE_NOT_READY",
                message="개인 Wiki Graph 저장소가 준비되지 않았습니다.",
                retryable=True,
            ),
        )
    return container.briefing_topics_service
