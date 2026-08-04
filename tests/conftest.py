"""테스트 전반에서 재사용하는 결정적 공통 픽스처와 저장소 대역.

프로덕션 코드의 인메모리 폴백을 제거했으므로, PostgreSQL 의미(컨텍스트
필수, 멱등 키 재사용, 단조 증가 버전)를 따르는 Fake 저장소를 테스트
전용으로 제공해 라우트 테스트가 실제 계약을 검증하게 한다.
"""

import os

# app.main은 import 시점에 create_app()을 실행해 로깅까지 구성한다(uvicorn 진입점
# 부작용). 테스트가 저장소 logs/에 파일을 쓰지 않도록 그 import보다 먼저 파일
# 로그를 끈다 — configure_logging은 최초 1회만 적용되기 때문이다.
os.environ["LOG_DIR"] = ""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import AppContainer, create_container
from app.main import create_app
from app.services.agent_jobs import (
    AgentJobRecord,
    ClaimedJobRecord,
    StoredUserContextRecord,
    SubmittedGenerationJob,
    SubmittedSourceJob,
)
from app.services.mvp import AgentApiMvpService
from app.services.publish_snapshots import PublishSnapshotService
from infrastructure.persistence.api import (
    GeneratedContentNotFoundError,
    StaleContextVersionError,
    UserContextRequiredError,
)
from shared.contracts import FeatureRequest

TEST_INTERNAL_TOKEN = "test-agent-internal-token-0123456789abcdef"
TEST_AUTHORIZATION_HEADER = {
    "Authorization": f"Bearer {TEST_INTERNAL_TOKEN}",
}


def _utc_now() -> datetime:
    """Timezone 정보가 포함된 현재 UTC 시각을 반환한다."""
    return datetime.now(UTC)


class InMemoryAgentJobRepository:
    """PostgreSQL Agent Job 저장소의 계약을 흉내 내는 테스트 대역."""

    def __init__(self) -> None:
        """컨텍스트, Job, 멱등 키와 생성 콘텐츠 저장소를 초기화한다."""
        self._contexts: dict[str, StoredUserContextRecord] = {}
        self._jobs: dict[str, AgentJobRecord] = {}
        self._idempotency: dict[tuple[str, str, str], str] = {}
        self._generated_contents: set[tuple[str, str]] = set()
        self._feedback_events: set[tuple[str, str]] = set()

    def register_generated_content(self, user_id: str, content_id: str) -> None:
        """위키마킹 대상이 될 생성 콘텐츠를 테스트용으로 등록한다."""
        self._generated_contents.add((user_id, content_id))

    async def submit_feedback_signals(
        self,
        *,
        user_id: str,
        signals: list[dict[str, Any]],
    ) -> int:
        """source_event_id 중복을 제외한 신호 저장 수를 반환한다."""
        accepted = 0
        for signal in signals:
            key = (user_id, str(signal.get("source_event_id")))
            if key in self._feedback_events:
                continue
            self._feedback_events.add(key)
            accepted += 1
        return accepted

    def _submit_job(
        self,
        *,
        feature_id: str,
        job_type: str,
        user_id: str,
        idempotency_key: str,
        request_id: str,
    ) -> tuple[AgentJobRecord, bool]:
        """멱등 키로 기존 Job을 재사용하거나 새 queued Job을 만든다."""
        key = (feature_id, user_id, idempotency_key)
        if existing_id := self._idempotency.get(key):
            return self._jobs[existing_id], False
        now = _utc_now()
        record = AgentJobRecord(
            job_id=uuid4().hex,
            feature_id=feature_id,
            job_type=job_type,
            user_id=user_id,
            idempotency_key=idempotency_key,
            status="queued",
            progress=0,
            request_id=request_id,
            created_at=now,
            updated_at=now,
        )
        self._jobs[record.job_id] = record
        self._idempotency[key] = record.job_id
        return record, True

    async def upsert_user_context(
        self,
        *,
        user_id: str,
        context_version: int,
        plan: str,
        preferred_language: str,
        personalization_enabled: bool,
        interest_taxonomy_version: str | None,
        selected_category_ids: list[str],
        selected_topic_ids: list[str],
        blocked_interest_ids: list[str],
        blocked_source_ids: list[str],
        signup_interests: list[dict[str, Any]],
    ) -> StoredUserContextRecord:
        """단조 증가 버전만 허용하며 새 Context Snapshot을 저장한다."""
        current = self._contexts.get(user_id)
        if current is not None and context_version <= current.context_version:
            raise StaleContextVersionError(user_id)
        stored = StoredUserContextRecord(
            user_id=user_id,
            context_version=context_version,
            plan=plan,
            preferred_language=preferred_language,
            personalization_enabled=personalization_enabled,
            interest_taxonomy_version=interest_taxonomy_version,
            selected_category_ids=list(selected_category_ids),
            selected_topic_ids=list(selected_topic_ids),
            blocked_interest_ids=list(blocked_interest_ids),
            blocked_source_ids=list(blocked_source_ids),
            signup_interests=[
                {"category": str(item["category"]), "topics": list(item.get("topics", []))}
                for item in signup_interests
            ],
            created_at=_utc_now(),
        )
        self._contexts[user_id] = stored
        return stored

    async def submit_web_clipping(
        self,
        *,
        user_id: str,
        source_event_id: str,
        source_url: str,
        title: str,
        content: str,
        author: str | None,
        published_at: datetime | None,
        clipped_on: date | None,
        description: str | None,
        tags: list[str],
        occurred_at: datetime | None,
        memo: str | None,
        request_id: str,
    ) -> SubmittedSourceJob:
        """클리핑을 멱등 접수하고 Wiki Build Job과 원본 ID를 반환한다."""
        record, _created = self._submit_job(
            feature_id="SVC-002",
            job_type="personal_wiki_build",
            user_id=user_id,
            idempotency_key=source_event_id,
            request_id=request_id,
        )
        return SubmittedSourceJob(
            job=record,
            source_document_id=f"source-{record.job_id[:8]}",
            source_document_version_id=f"version-{record.job_id[:8]}",
        )

    async def submit_url_source(
        self,
        *,
        user_id: str,
        source_event_id: str,
        url: str,
        occurred_at: datetime | None,
        memo: str | None,
        request_id: str,
    ) -> SubmittedSourceJob:
        """URL 원본을 멱등 접수하고 수집 Job을 반환한다."""
        record, _created = self._submit_job(
            feature_id="SVC-003",
            job_type="personal_wiki_url",
            user_id=user_id,
            idempotency_key=source_event_id,
            request_id=request_id,
        )
        return SubmittedSourceJob(
            job=record,
            source_document_id=f"source-{record.job_id[:8]}",
            source_document_version_id=None,
        )

    async def submit_content_mark(
        self,
        *,
        user_id: str,
        source_event_id: str,
        content_id: str,
        occurred_at: datetime | None,
        memo: str | None,
        request_id: str,
    ) -> SubmittedSourceJob:
        """등록된 생성 콘텐츠만 멱등 접수하고 Wiki Build Job을 반환한다."""
        if (user_id, content_id) not in self._generated_contents:
            raise GeneratedContentNotFoundError(content_id)
        record, _created = self._submit_job(
            feature_id="SVC-004",
            job_type="personal_wiki_build",
            user_id=user_id,
            idempotency_key=source_event_id,
            request_id=request_id,
        )
        return SubmittedSourceJob(
            job=record,
            source_document_id=f"source-{record.job_id[:8]}",
            source_document_version_id=f"version-{record.job_id[:8]}",
        )

    async def submit_generation(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        topic: str,
        content_type: str,
        language: str | None,
        scheduled_at: datetime | None = None,
        request_id: str,
    ) -> SubmittedGenerationJob:
        """실제 저장소처럼 컨텍스트를 요구하며 생성 Job을 멱등 접수한다."""
        if user_id not in self._contexts:
            raise UserContextRequiredError(user_id)
        record, _created = self._submit_job(
            feature_id="SVC-008",
            job_type="report_generation",
            user_id=user_id,
            idempotency_key=idempotency_key,
            request_id=request_id,
        )
        return SubmittedGenerationJob(
            job=record,
            generation_request_id=f"generation-{record.job_id[:8]}",
        )

    async def get_job(self, job_id: str) -> AgentJobRecord | None:
        """저장된 Job 레코드를 반환한다."""
        return self._jobs.get(job_id)

    async def claim_job(
        self, *, job_id: str, worker_id: str, lease_seconds: int
    ) -> ClaimedJobRecord | None:
        """라우트 테스트에서는 점유가 필요 없어 항상 None을 반환한다."""
        return None

    async def list_runnable_jobs(
        self, *, job_type: str, user_id: str | None = None, limit: int
    ) -> list[str]:
        """라우트 테스트에서는 대기 Job 목록이 필요 없어 빈 목록을 반환한다."""
        return []

    async def save_fetched_url(self, **_: object) -> dict[str, object]:
        """URL 저장은 라우트 테스트 범위가 아니므로 빈 결과를 반환한다."""
        return {}

    @asynccontextmanager
    async def acquire_connection(self) -> AsyncIterator[object]:
        """그래프 실행 대역에 빌려줄 연결 객체를 반환한다."""
        yield object()

    async def complete_job(self, **_: object) -> None:
        """Worker 완료 계약은 라우트 테스트 범위가 아니다."""
        return None

    async def fail_job(self, **_: object) -> str:
        """Worker 실패 계약은 라우트 테스트 범위가 아니다."""
        return "failed"

    def finish_job(self, job_id: str, result: dict[str, object]) -> None:
        """테스트가 Worker 완료를 흉내 내 Job 결과를 기록하게 한다."""
        record = self._jobs[job_id]
        now = _utc_now()
        self._jobs[job_id] = AgentJobRecord(
            job_id=record.job_id,
            feature_id=record.feature_id,
            job_type=record.job_type,
            user_id=record.user_id,
            idempotency_key=record.idempotency_key,
            status="completed",
            progress=100,
            request_id=record.request_id,
            created_at=record.created_at,
            updated_at=now,
            result=result,
            completed_at=now,
        )


@pytest.fixture
def feature_request() -> FeatureRequest:
    """외부 호출 없이 사용할 수 있는 공통 기능 요청을 반환한다."""
    return FeatureRequest(request_id="test-request", actor_id="test-service")


@pytest.fixture
def settings() -> Settings:
    """외부 연결 없이 실행할 수 있는 테스트 설정을 반환한다."""
    return Settings(
        app_name="Test Report Builder Agent API",
        app_version="9.9.9",
        environment="test",
        internal_api_token=TEST_INTERNAL_TOKEN,
    )


@pytest.fixture
def agent_jobs_fake() -> InMemoryAgentJobRepository:
    """실 DB 계약을 따르는 테스트 전용 Agent Job 저장소를 반환한다."""
    return InMemoryAgentJobRepository()


@pytest.fixture
def container(
    settings: Settings, agent_jobs_fake: InMemoryAgentJobRepository
) -> AppContainer:
    """Fake 저장소가 주입된 독립 애플리케이션 컨테이너를 반환한다."""
    application_container = create_container(settings)
    application_container.mvp_service = AgentApiMvpService(agent_jobs_fake)
    return application_container


@pytest.fixture
def mvp_service(container: AppContainer) -> AgentApiMvpService:
    """테스트 컨테이너의 MVP 서비스를 반환한다."""
    assert container.mvp_service is not None
    return container.mvp_service


@pytest.fixture
def publish_service(container: AppContainer) -> PublishSnapshotService:
    """테스트 컨테이너의 발행 Snapshot 서비스를 반환한다."""
    assert container.publish_snapshot_service is not None
    return container.publish_snapshot_service


@pytest.fixture
def client(settings: Settings, container: AppContainer) -> Iterator[TestClient]:
    """Lifespan이 활성화된 FastAPI 테스트 클라이언트를 제공한다."""
    with TestClient(create_app(settings, container)) as test_client:
        test_client.headers.update(TEST_AUTHORIZATION_HEADER)
        yield test_client
