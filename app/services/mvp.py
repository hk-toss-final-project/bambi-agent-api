"""FastAPI MVP 엔드포인트를 지원하는 애플리케이션 서비스.

Queue Adapter가 구현되기 전에도 API 계약과 멱등성, 상태 전이를 검증할 수
있도록 최소 상태를 보관하고 Publish Snapshot 저장소 경계를 조정한다.
"""

from asyncio import Lock
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import status

from app.exceptions import AgentApiError, ErrorDetail
from app.schemas.mvp import (
    AcceptedJobResponse,
    GenerationRequest,
    JobResultResponse,
    JobStatus,
    JobStatusResponse,
    PublishAckRequest,
    PublishAckResponse,
    PublishBatchAckRequest,
    PublishBatchAckResponse,
    PublishBatchClaimRequest,
    PublishBatchClaimResponse,
    PublishSnapshotResponse,
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
from app.services.publish_snapshots import (
    InMemoryPublishSnapshotRepository,
    PublishBatchLeaseExpiredError,
    PublishBatchNotFoundError,
    PublishBatchOwnershipMismatchError,
    PublishSnapshotMismatchError,
    PublishSnapshotNotFoundError,
    PublishSnapshotRepository,
    StalePublishSnapshotError,
)
from infrastructure.persistence.api import (
    StaleContextVersionError,
    UserContextRequiredError,
)


def utc_now() -> datetime:
    """Timezone 정보가 포함된 현재 UTC 시각을 반환한다."""
    return datetime.now(UTC)


class AgentApiMvpService:
    """MVP API 계약을 실행하고 기능별 상태 저장소를 조정한다."""

    def __init__(
        self,
        publish_snapshot_repository: PublishSnapshotRepository | None = None,
        agent_job_repository: AgentJobRepository | None = None,
    ) -> None:
        """사용자 컨텍스트, Job과 Publish Snapshot 저장소를 초기화한다."""
        self._contexts: dict[str, UserContextResponse] = {}
        self._jobs: dict[str, JobStatusResponse] = {}
        self._job_results: dict[str, JobResultResponse] = {}
        self._job_payloads: dict[str, dict[str, object]] = {}
        self._job_keys: dict[tuple[str, str, str], str] = {}
        self._publish_snapshots = (
            publish_snapshot_repository or InMemoryPublishSnapshotRepository()
        )
        self._agent_jobs = agent_job_repository
        self._lock = Lock()

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
        """클리핑을 DB에 영속화하거나 인메모리 호환 Job으로 접수한다."""
        if self._agent_jobs is None:
            return await self.enqueue_job(
                feature_id="SVC-002",
                job_type="personal_wiki_web_clipping",
                user_id=user_id,
                idempotency_key=payload.source_event_id,
                request_id=request_id,
                payload=payload.model_dump(mode="json"),
            )
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
        """URL을 DB에 영속화하거나 인메모리 호환 Job으로 접수한다."""
        if self._agent_jobs is None:
            return await self.enqueue_job(
                feature_id="SVC-003",
                job_type="personal_wiki_url",
                user_id=user_id,
                idempotency_key=payload.source_event_id,
                request_id=request_id,
                payload=payload.model_dump(mode="json"),
            )
        submission = await self._agent_jobs.submit_url_source(
            user_id=user_id,
            source_event_id=payload.source_event_id,
            url=str(payload.url),
            occurred_at=payload.occurred_at,
            memo=payload.memo,
            request_id=request_id,
        )
        return self._accepted_job_response(submission)

    async def submit_generation(
        self,
        *,
        user_id: str,
        payload: GenerationRequest,
        request_id: str,
    ) -> AcceptedJobResponse:
        """Bambi 생성 요청을 DB 또는 인메모리 호환 Job으로 접수한다."""
        if self._agent_jobs is None:
            return await self.enqueue_job(
                feature_id="SVC-008",
                job_type="bambi_generation",
                user_id=user_id,
                idempotency_key=payload.idempotency_key,
                request_id=request_id,
                payload=payload.model_dump(mode="json"),
            )
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
        if self._agent_jobs is not None:
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
        async with self._lock:
            current = self._contexts.get(user_id)
            if current and payload.context_version <= current.context_version:
                raise AgentApiError(
                    status.HTTP_409_CONFLICT,
                    ErrorDetail(
                        code="STALE_CONTEXT_VERSION",
                        message="현재 버전보다 새로운 사용자 컨텍스트가 필요합니다.",
                    ),
                )
            response = UserContextResponse(
                user_id=user_id,
                context_version=payload.context_version,
                plan=payload.plan,
                preferred_language=payload.preferred_language,
                personalization_enabled=payload.personalization_enabled,
                blocked_interest_ids=payload.blocked_interest_ids,
                blocked_source_ids=payload.blocked_source_ids,
                updated_at=utc_now(),
                request_id=request_id,
            )
            self._contexts[user_id] = response
            return response

    async def enqueue_job(
        self,
        *,
        feature_id: str,
        job_type: str,
        user_id: str,
        idempotency_key: str,
        request_id: str,
        payload: dict[str, object],
    ) -> AcceptedJobResponse:
        """멱등성 키로 중복 등록을 막고 처리 대기 Job을 생성한다."""
        async with self._lock:
            key = (feature_id, user_id, idempotency_key)
            if existing_job_id := self._job_keys.get(key):
                existing = self._jobs[existing_job_id]
                return AcceptedJobResponse(**existing.model_dump())
            now = utc_now()
            job_id = uuid4().hex
            record = JobStatusResponse(
                job_id=job_id,
                feature_id=feature_id,
                status=JobStatus.QUEUED,
                request_id=request_id,
                created_at=now,
                user_id=user_id,
                job_type=job_type,
                updated_at=now,
            )
            self._jobs[job_id] = record
            self._job_payloads[job_id] = payload
            self._job_keys[key] = job_id
            return AcceptedJobResponse(**record.model_dump())

    async def get_job_payload(self, job_id: str) -> dict[str, object]:
        """Worker가 처리할 원본 Job Payload를 반환한다."""
        await self.get_job(job_id)
        return self._job_payloads[job_id].copy()

    async def get_job(self, job_id: str) -> JobStatusResponse:
        """식별자에 해당하는 Agent Job 상태를 조회한다."""
        if self._agent_jobs is not None:
            record = await self._agent_jobs.get_job(job_id)
            if record is not None:
                return self._job_status_response(record)
            raise AgentApiError(
                status.HTTP_404_NOT_FOUND,
                ErrorDetail(
                    code="JOB_NOT_FOUND", message="Agent Job을 찾을 수 없습니다."
                ),
            )
        if record := self._jobs.get(job_id):
            return record
        raise AgentApiError(
            status.HTTP_404_NOT_FOUND,
            ErrorDetail(code="JOB_NOT_FOUND", message="Agent Job을 찾을 수 없습니다."),
        )

    async def get_job_result(self, job_id: str) -> JobResultResponse:
        """완료된 Agent Job의 결과를 반환하고 미완료 상태는 충돌로 알린다."""
        if self._agent_jobs is not None:
            record = await self._agent_jobs.get_job(job_id)
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
        record = await self.get_job(job_id)
        if result := self._job_results.get(job_id):
            return result
        raise AgentApiError(
            status.HTTP_409_CONFLICT,
            ErrorDetail(
                code="JOB_RESULT_NOT_READY",
                message=f"Agent Job 결과가 아직 준비되지 않았습니다: {record.status}",
                retryable=True,
            ),
        )

    async def complete_job(
        self, job_id: str, result: dict[str, object]
    ) -> JobResultResponse:
        """Worker가 완료한 Job 결과를 저장하고 상태와 진행률을 갱신한다."""
        async with self._lock:
            record = await self.get_job(job_id)
            completed_at = utc_now()
            self._jobs[job_id] = record.model_copy(
                update={
                    "status": JobStatus.COMPLETED,
                    "progress": 100,
                    "updated_at": completed_at,
                }
            )
            response = JobResultResponse(
                job_id=job_id,
                feature_id=record.feature_id,
                status=JobStatus.COMPLETED,
                result=result,
                completed_at=completed_at,
            )
            self._job_results[job_id] = response
            return response

    async def save_publish_snapshot(self, snapshot: PublishSnapshotResponse) -> None:
        """Bambi Worker가 생성한 최신 발행 Snapshot을 저장한다."""
        try:
            await self._publish_snapshots.save(snapshot)
        except StalePublishSnapshotError as exc:
            raise AgentApiError(
                status.HTTP_409_CONFLICT,
                ErrorDetail(
                    code="STALE_SNAPSHOT_VERSION",
                    message="현재보다 새로운 Snapshot 버전이 필요합니다.",
                ),
            ) from exc

    async def get_publish_snapshot(self, content_id: str) -> PublishSnapshotResponse:
        """Service Worker가 저장할 최신 발행 Snapshot을 반환한다."""
        if snapshot := await self._publish_snapshots.get_latest(content_id):
            return snapshot
        raise AgentApiError(
            status.HTTP_404_NOT_FOUND,
            ErrorDetail(
                code="PUBLISH_SNAPSHOT_NOT_FOUND",
                message="발행 Snapshot을 찾을 수 없습니다.",
            ),
        )

    async def acknowledge_publish(
        self, content_id: str, payload: PublishAckRequest
    ) -> PublishAckResponse:
        """Snapshot 버전과 Hash를 확인한 뒤 Service Worker의 발행 ACK를 기록한다."""
        try:
            acknowledged_at = await self._publish_snapshots.acknowledge(
                content_id, payload
            )
        except PublishSnapshotNotFoundError as exc:
            raise AgentApiError(
                status.HTTP_404_NOT_FOUND,
                ErrorDetail(
                    code="PUBLISH_SNAPSHOT_NOT_FOUND",
                    message="발행 Snapshot을 찾을 수 없습니다.",
                ),
            ) from exc
        except PublishSnapshotMismatchError as exc:
            raise AgentApiError(
                status.HTTP_409_CONFLICT,
                ErrorDetail(
                    code="PUBLISH_SNAPSHOT_MISMATCH",
                    message="ACK의 Snapshot 버전 또는 Hash가 일치하지 않습니다.",
                ),
            ) from exc
        return PublishAckResponse(
            content_id=content_id,
            version=payload.version,
            status=payload.status,
            acknowledged_at=acknowledged_at,
        )

    async def claim_publish_snapshot_batch(
        self, payload: PublishBatchClaimRequest
    ) -> PublishBatchClaimResponse:
        """Service Worker가 처리할 Publish Snapshot Batch를 Lease와 함께 반환한다."""
        return await self._publish_snapshots.claim_batch(payload)

    async def acknowledge_publish_snapshot_batch(
        self, batch_id: str, payload: PublishBatchAckRequest
    ) -> PublishBatchAckResponse:
        """Service Worker의 항목별 Batch 발행 결과를 저장소에 반영한다."""
        try:
            return await self._publish_snapshots.acknowledge_batch(batch_id, payload)
        except PublishBatchNotFoundError as exc:
            raise AgentApiError(
                status.HTTP_404_NOT_FOUND,
                ErrorDetail(
                    code="PUBLISH_BATCH_NOT_FOUND",
                    message="Publish Snapshot Batch를 찾을 수 없습니다.",
                ),
            ) from exc
        except PublishBatchOwnershipMismatchError as exc:
            raise AgentApiError(
                status.HTTP_409_CONFLICT,
                ErrorDetail(
                    code="PUBLISH_BATCH_OWNERSHIP_MISMATCH",
                    message="Batch를 Claim한 Worker와 ACK Worker가 다릅니다.",
                ),
            ) from exc
        except PublishBatchLeaseExpiredError as exc:
            raise AgentApiError(
                status.HTTP_409_CONFLICT,
                ErrorDetail(
                    code="PUBLISH_BATCH_LEASE_EXPIRED",
                    message="Batch Lease가 만료되어 ACK를 반영할 수 없습니다.",
                    retryable=True,
                ),
            ) from exc
        except PublishSnapshotMismatchError as exc:
            raise AgentApiError(
                status.HTTP_409_CONFLICT,
                ErrorDetail(
                    code="PUBLISH_SNAPSHOT_MISMATCH",
                    message="ACK 항목의 Snapshot 버전 또는 Hash가 일치하지 않습니다.",
                ),
            ) from exc
