"""FastAPI MVP 원본 접수·사용자 컨텍스트·Job 조회 애플리케이션 서비스.

PostgreSQL Agent Job 저장소를 필수로 사용한다. 저장소가 없는 런타임은
컨테이너가 서비스를 만들지 않으며 라우터가 SERVICE_NOT_READY를 반환한다.
발행 Snapshot 조정은 PublishSnapshotService가 담당한다.
"""

from fastapi import status

from app.exceptions import AgentApiError, ErrorDetail
from app.schemas.mvp import (
    AcceptedJobResponse,
    ContentMarkRequest,
    GenerationRequest,
    JobResultResponse,
    JobStatus,
    JobStatusResponse,
    UserContextResponse,
    UserContextUpsertRequest,
    UrlWikiSourceRequest,
    WebClippingRequest,
)
from app.services.agent_jobs import (
    AgentJobRecord,
    AgentJobRepository,
    SubmittedGenerationJob,
    SubmittedSourceJob,
)
from domain.jobs.api import job_002
from domain.personal_wiki.source_events.api import wse_001, wse_011
from infrastructure.persistence.api import (
    StaleContextVersionError,
    UserContextRequiredError,
)


class AgentApiMvpService:
    """MVP API 계약(컨텍스트·원본 접수·생성 접수·Job 조회)을 실행한다."""

    def __init__(self, agent_job_repository: AgentJobRepository) -> None:
        """사용자 원본·Job PostgreSQL 저장소를 주입한다."""
        self._agent_jobs = agent_job_repository

    @staticmethod
    def _accepted_job_response(
        submission: SubmittedSourceJob,
    ) -> AcceptedJobResponse:
        """저장소 원본 접수 결과를 202 응답으로 변환한다."""
        job = submission.job
        return AcceptedJobResponse(
            job_id=job.job_id,
            feature_id=job.feature_id,
            status=JobStatus(job.status),
            request_id=job.request_id,
            created_at=job.created_at,
            source_document_id=submission.source_document_id,
            source_document_version_id=submission.source_document_version_id,
        )

    @staticmethod
    def _job_status_response(record: AgentJobRecord) -> JobStatusResponse:
        """저장소 Job 레코드를 상태 조회 응답으로 변환한다."""
        return JobStatusResponse(
            job_id=record.job_id,
            feature_id=record.feature_id,
            status=JobStatus(record.status),
            request_id=record.request_id,
            created_at=record.created_at,
            user_id=record.user_id,
            job_type=record.job_type,
            progress=record.progress,
            updated_at=record.updated_at,
            error_code=record.error_code,
        )

    async def submit_web_clipping(
        self,
        *,
        user_id: str,
        payload: WebClippingRequest,
        request_id: str,
    ) -> AcceptedJobResponse:
        """클리핑 원본·Version·Wiki Build Job을 PostgreSQL에 영속화한다."""
        payload = await wse_001(payload)
        await wse_011(user_id, payload.source_event_id)
        submission = await self._agent_jobs.submit_web_clipping(
            user_id=user_id,
            source_event_id=payload.source_event_id,
            source_url=str(payload.source),
            title=payload.title,
            content=payload.content,
            author=payload.author,
            published_at=payload.published,
            clipped_on=payload.created,
            description=payload.description,
            tags=payload.tags,
            occurred_at=payload.occurred_at,
            memo=payload.memo,
            request_id=request_id,
        )
        return self._accepted_job_response(submission)

    async def submit_url_source(
        self,
        *,
        user_id: str,
        payload: UrlWikiSourceRequest,
        request_id: str,
    ) -> AcceptedJobResponse:
        """URL 원본 Head와 수집 Job을 PostgreSQL에 영속화한다."""
        submission = await self._agent_jobs.submit_url_source(
            user_id=user_id,
            source_event_id=payload.source_event_id,
            url=str(payload.url),
            occurred_at=payload.occurred_at,
            memo=payload.memo,
            request_id=request_id,
        )
        return self._accepted_job_response(submission)

    async def submit_content_mark(
        self,
        *,
        user_id: str,
        payload: ContentMarkRequest,
        request_id: str,
    ) -> AcceptedJobResponse:
        """[SVC-004] 위키마킹 접수 — 처리 Handler 구현 전까지 명시적 미구현.

        과거에는 인메모리 유령 Job으로 접수만 되고 아무도 처리하지 않았다.
        Handler(personal_wiki_content_mark)가 구현되기 전까지 501을 반환해
        미구현 상태를 호출자에게 정직하게 노출한다.
        """
        raise AgentApiError(
            status.HTTP_501_NOT_IMPLEMENTED,
            ErrorDetail(
                code="NOT_IMPLEMENTED",
                message="위키마킹 처리는 아직 구현되지 않았습니다.",
            ),
        )

    async def submit_generation(
        self,
        *,
        user_id: str,
        payload: GenerationRequest,
        request_id: str,
    ) -> AcceptedJobResponse:
        """Bambi 생성 요청과 Job을 사용자 컨텍스트에 연결해 멱등 접수한다."""
        try:
            submission: SubmittedGenerationJob = (
                await self._agent_jobs.submit_generation(
                    user_id=user_id,
                    idempotency_key=payload.idempotency_key,
                    topic=payload.topic,
                    content_type=payload.content_type,
                    language=payload.language,
                    scheduled_at=payload.scheduled_at,
                    request_id=request_id,
                )
            )
        except UserContextRequiredError as exc:
            raise AgentApiError(
                status.HTTP_409_CONFLICT,
                ErrorDetail(
                    code="USER_CONTEXT_REQUIRED",
                    message="콘텐츠 생성 전에 사용자 컨텍스트를 등록해야 합니다.",
                ),
            ) from exc
        job = submission.job
        return AcceptedJobResponse(
            job_id=job.job_id,
            feature_id=job.feature_id,
            status=JobStatus(job.status),
            request_id=job.request_id,
            created_at=job.created_at,
            generation_request_id=submission.generation_request_id,
        )

    async def upsert_user_context(
        self,
        user_id: str,
        payload: UserContextUpsertRequest,
        request_id: str,
    ) -> UserContextResponse:
        """최신 버전의 사용자 컨텍스트를 저장하고 이전 버전 덮어쓰기를 차단한다."""
        try:
            stored = await self._agent_jobs.upsert_user_context(
                user_id=user_id,
                context_version=payload.context_version,
                plan=payload.plan.value,
                preferred_language=payload.preferred_language,
                personalization_enabled=payload.personalization_enabled,
                blocked_interest_ids=payload.blocked_interest_ids,
                blocked_source_ids=payload.blocked_source_ids,
            )
        except StaleContextVersionError as exc:
            raise AgentApiError(
                status.HTTP_409_CONFLICT,
                ErrorDetail(
                    code="STALE_CONTEXT_VERSION",
                    message="현재 버전보다 새로운 사용자 컨텍스트가 필요합니다.",
                ),
            ) from exc
        return UserContextResponse(
            user_id=stored.user_id,
            context_version=stored.context_version,
            plan=stored.plan,
            preferred_language=stored.preferred_language,
            personalization_enabled=stored.personalization_enabled,
            blocked_interest_ids=stored.blocked_interest_ids,
            blocked_source_ids=stored.blocked_source_ids,
            updated_at=stored.created_at,
            request_id=request_id,
        )

    async def get_job(self, job_id: str) -> JobStatusResponse:
        """식별자에 해당하는 Agent Job 상태를 조회한다."""
        record = await job_002(self._agent_jobs, job_id)
        if record is not None:
            return self._job_status_response(record)
        raise AgentApiError(
            status.HTTP_404_NOT_FOUND,
            ErrorDetail(code="JOB_NOT_FOUND", message="Agent Job을 찾을 수 없습니다."),
        )

    async def get_job_result(self, job_id: str) -> JobResultResponse:
        """완료된 Agent Job의 결과를 반환하고 미완료 상태는 충돌로 알린다."""
        record = await job_002(self._agent_jobs, job_id)
        if record is None:
            raise AgentApiError(
                status.HTTP_404_NOT_FOUND,
                ErrorDetail(
                    code="JOB_NOT_FOUND", message="Agent Job을 찾을 수 없습니다."
                ),
            )
        if record.status == JobStatus.COMPLETED.value and record.result is not None:
            return JobResultResponse(
                job_id=record.job_id,
                feature_id=record.feature_id,
                status=JobStatus.COMPLETED,
                result=record.result,
                completed_at=record.completed_at or record.updated_at,
            )
        raise AgentApiError(
            status.HTTP_409_CONFLICT,
            ErrorDetail(
                code="JOB_RESULT_NOT_READY",
                message=(
                    "Agent Job 결과가 아직 준비되지 않았습니다: "
                    f"{record.status}"
                ),
                retryable=True,
            ),
        )
