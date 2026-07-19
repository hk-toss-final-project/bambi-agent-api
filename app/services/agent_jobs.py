"""Agent Job과 사용자 원본 저장소의 애플리케이션 계약.

FastAPI 서비스가 PostgreSQL 구현 세부사항을 알지 않도록 원본 접수, Job 조회,
개발용 동기 실행에 필요한 데이터 객체와 Repository Protocol을 정의한다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AgentJobRecord:
    """저장소에서 조회한 Agent Job의 현재 상태."""

    job_id: str
    feature_id: str
    job_type: str
    user_id: str
    idempotency_key: str
    status: str
    progress: int
    request_id: str
    created_at: datetime
    updated_at: datetime
    error_code: str | None = None
    result: dict[str, object] | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ClaimedJobRecord:
    """개발 실행기 또는 Worker가 Lease로 점유한 Agent Job."""

    job_id: str
    user_id: str
    feature_id: str
    job_type: str
    attempt_number: int
    max_attempts: int
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SubmittedSourceJob:
    """사용자 원본 저장과 함께 등록되거나 재사용된 Agent Job."""

    job: AgentJobRecord
    source_document_id: str
    source_document_version_id: str | None


@dataclass(frozen=True, slots=True)
class StoredUserContextRecord:
    """PostgreSQL에 저장된 사용자 Context Snapshot의 애플리케이션 표현."""

    user_id: str
    context_version: int
    plan: str
    preferred_language: str
    personalization_enabled: bool
    blocked_interest_ids: list[str]
    blocked_source_ids: list[str]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SubmittedGenerationJob:
    """Bambi Generation Job과 생성 요청 접수 결과."""

    job: AgentJobRecord
    generation_request_id: str


class AgentJobRepository(Protocol):
    """원본 접수와 Agent Job 실행에 필요한 저장소 계약."""

    async def upsert_user_context(
        self,
        *,
        user_id: str,
        context_version: int,
        plan: str,
        preferred_language: str,
        personalization_enabled: bool,
        blocked_interest_ids: list[str],
        blocked_source_ids: list[str],
    ) -> StoredUserContextRecord:
        """새 사용자 Context Snapshot을 PostgreSQL에 저장한다."""
        ...

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
        """클리핑 원본 Version과 Personal Wiki Build Job을 저장한다."""
        ...

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
        """URL 원본 Head와 URL 수집 Job을 저장한다."""
        ...

    async def submit_generation(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        topic: str,
        content_type: str,
        language: str | None,
        request_id: str,
    ) -> SubmittedGenerationJob:
        """Bambi Generation Job과 생성 요청을 멱등 저장한다."""
        ...

    async def get_job(self, job_id: str) -> AgentJobRecord | None:
        """Agent Job의 현재 저장 상태를 반환한다."""
        ...

    async def claim_job(
        self, *, job_id: str, worker_id: str, lease_seconds: int
    ) -> ClaimedJobRecord | None:
        """실행 가능한 Job을 지정한 Worker가 Lease로 점유한다."""
        ...

    async def save_fetched_url(
        self,
        *,
        job: ClaimedJobRecord,
        title: str,
        markdown: str,
        resolved_url: str,
        published_at: datetime | None,
    ) -> dict[str, object]:
        """URL 수집 결과를 원본 Version으로 저장하고 Wiki Job을 등록한다."""
        ...

    async def build_personal_wiki(
        self, *, job: ClaimedJobRecord, model: str
    ) -> dict[str, object]:
        """점유한 Wiki Job의 원본으로 증분 Wiki Build를 실행한다."""
        ...

    async def build_bambi_content(
        self, *, job: ClaimedJobRecord, model: str
    ) -> dict[str, object]:
        """개인·Global Context로 Bambi 콘텐츠를 생성하고 저장한다."""
        ...

    async def complete_job(
        self,
        *,
        job: ClaimedJobRecord,
        worker_id: str,
        result: dict[str, object],
    ) -> None:
        """Job과 Attempt를 완료 상태로 저장한다."""
        ...

    async def fail_job(
        self,
        *,
        job: ClaimedJobRecord,
        worker_id: str,
        error_code: str,
        error_message: str,
        retryable: bool,
    ) -> str:
        """Job 실패와 재시도 상태를 저장한다."""
        ...
