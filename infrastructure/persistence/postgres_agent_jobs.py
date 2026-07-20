"""PostgreSQL 기반 사용자 원본·Agent Job Repository.

Service API의 원본 접수와 Job 조회, 개발 실행기의 Lease·완료·실패 처리 및
Personal Wiki Build에 하나의 연결 Pool을 제공한다.
"""

import asyncio
from datetime import date, datetime
from time import monotonic
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent.bambi.api import generate_bambi_content
from agent.wiki_builder.api import build_incremental_wiki
from app.services.agent_jobs import (
    AgentJobRecord,
    ClaimedJobRecord,
    StoredUserContextRecord,
    SubmittedGenerationJob,
    SubmittedSourceJob,
)
from infrastructure.persistence.api import (
    ClaimedAgentJob,
    claim_agent_job_by_id,
    complete_agent_job,
    enqueue_personal_wiki_build_job,
    fail_agent_job,
    get_agent_job,
    enqueue_bambi_generation_job,
    list_runnable_agent_jobs,
    load_bambi_context,
    mark_url_source_event,
    register_url_and_enqueue,
    save_user_url_document_version,
    save_web_clipping_and_enqueue,
    set_personal_wiki_scope,
    set_system_job_scope,
    persist_bambi_generation,
    upsert_user_context_snapshot,
)

type DictRow = dict[str, Any]


class PostgresAgentJobRepository:
    """PostgreSQL에서 사용자 원본과 Agent Job 수명주기를 관리한다."""

    def __init__(self, database_url: str) -> None:
        """지연 시작 방식의 Agent Job PostgreSQL Pool을 구성한다."""
        self._pool: AsyncConnectionPool[DictRow] = AsyncConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=4,
            open=False,
            kwargs={"row_factory": dict_row},
        )

    async def startup(self) -> None:
        """원본·Job 저장용 연결 Pool을 열고 준비될 때까지 기다린다."""
        await self._pool.open(wait=True)

    async def shutdown(self) -> None:
        """원본·Job 저장용 연결 Pool을 종료한다."""
        await self._pool.close()

    @staticmethod
    def _to_job_record(stored: Any) -> AgentJobRecord:
        """Persistence Job 객체를 애플리케이션 Job 레코드로 변환한다."""
        return AgentJobRecord(
            job_id=stored.job_id,
            feature_id=stored.feature_id,
            job_type=stored.job_type,
            user_id=stored.user_id,
            idempotency_key=stored.idempotency_key,
            status=stored.status,
            progress=stored.progress,
            request_id=stored.request_id,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
            error_code=stored.error_code,
            result=stored.result,
            completed_at=stored.completed_at,
        )

    @staticmethod
    def _to_claimed_record(job: ClaimedAgentJob) -> ClaimedJobRecord:
        """Persistence Lease 객체를 실행기가 사용할 Job 레코드로 변환한다."""
        return ClaimedJobRecord(
            job_id=job.job_id,
            user_id=job.user_id,
            feature_id=job.feature_id,
            job_type=job.job_type,
            attempt_number=job.attempt_number,
            max_attempts=job.max_attempts,
            payload=dict(job.payload),
        )

    @staticmethod
    def _to_claimed_job(job: ClaimedJobRecord) -> ClaimedAgentJob:
        """애플리케이션 Lease 객체를 Persistence 완료 함수 형식으로 변환한다."""
        return ClaimedAgentJob(
            job_id=job.job_id,
            user_id=job.user_id,
            feature_id=job.feature_id,
            job_type=job.job_type,
            attempt_number=job.attempt_number,
            max_attempts=job.max_attempts,
            payload=dict(job.payload),
        )

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
        """클리핑 원본과 Wiki Build Job을 저장하고 조회 가능한 결과를 반환한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await set_personal_wiki_scope(connection, user_id=user_id)
                saved = await save_web_clipping_and_enqueue(
                    connection,
                    user_id=user_id,
                    source_event_id=source_event_id,
                    source_url=source_url,
                    title=title,
                    content=content,
                    author=author,
                    published_at=published_at,
                    clipped_on=clipped_on,
                    description=description,
                    tags=tags,
                    occurred_at=occurred_at,
                    memo=memo,
                    request_id=request_id,
                )
                stored = await get_agent_job(connection, job_id=saved.job_id)
                if stored is None:
                    raise RuntimeError(f"저장한 Wiki Job을 찾을 수 없습니다: {saved.job_id}")
        return SubmittedSourceJob(
            job=self._to_job_record(stored),
            source_document_id=saved.source_document_id,
            source_document_version_id=saved.source_document_version_id,
        )

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
        """사용자 Context를 사용자 RLS Scope의 새 Snapshot으로 저장한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await set_personal_wiki_scope(connection, user_id=user_id)
                stored = await upsert_user_context_snapshot(
                    connection,
                    user_id=user_id,
                    context_version=context_version,
                    plan=plan,
                    preferred_language=preferred_language,
                    personalization_enabled=personalization_enabled,
                    blocked_interest_ids=blocked_interest_ids,
                    blocked_source_ids=blocked_source_ids,
                )
        return StoredUserContextRecord(
            user_id=stored.user_id,
            context_version=stored.context_version,
            plan=stored.plan,
            preferred_language=stored.preferred_language,
            personalization_enabled=stored.personalization_enabled,
            blocked_interest_ids=stored.blocked_interest_ids,
            blocked_source_ids=stored.blocked_source_ids,
            created_at=stored.created_at,
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
        """URL 원본 Head와 수집 Job을 저장하고 조회 가능한 결과를 반환한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await set_personal_wiki_scope(connection, user_id=user_id)
                saved = await register_url_and_enqueue(
                    connection,
                    user_id=user_id,
                    source_event_id=source_event_id,
                    url=url,
                    occurred_at=occurred_at,
                    memo=memo,
                    request_id=request_id,
                )
                stored = await get_agent_job(connection, job_id=saved.job_id)
                if stored is None:
                    raise RuntimeError(f"저장한 URL Job을 찾을 수 없습니다: {saved.job_id}")
        return SubmittedSourceJob(
            job=self._to_job_record(stored),
            source_document_id=saved.source_document_id,
            source_document_version_id=saved.source_document_version_id,
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
        """Bambi Generation Job과 요청을 사용자 Context에 연결해 저장한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await set_personal_wiki_scope(connection, user_id=user_id)
                submitted = await enqueue_bambi_generation_job(
                    connection,
                    user_id=user_id,
                    idempotency_key=idempotency_key,
                    topic=topic,
                    content_type=content_type,
                    language=language,
                    scheduled_at=scheduled_at,
                    request_id=request_id,
                )
                stored = await get_agent_job(connection, job_id=submitted.job_id)
                if stored is None:
                    raise RuntimeError(
                        f"저장한 Bambi Job을 찾을 수 없습니다: {submitted.job_id}"
                    )
        return SubmittedGenerationJob(
            job=self._to_job_record(stored),
            generation_request_id=submitted.generation_request_id,
        )

    async def get_job(self, job_id: str) -> AgentJobRecord | None:
        """시스템 Scope로 Agent Job 상태와 결과를 조회한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await set_system_job_scope(connection)
                stored = await get_agent_job(connection, job_id=job_id)
        return self._to_job_record(stored) if stored is not None else None

    async def claim_job(
        self, *, job_id: str, worker_id: str, lease_seconds: int
    ) -> ClaimedJobRecord | None:
        """지정한 Agent Job 하나를 시스템 Scope에서 Lease로 점유한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await set_system_job_scope(connection)
                claimed = await claim_agent_job_by_id(
                    connection,
                    job_id=job_id,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                )
        return self._to_claimed_record(claimed) if claimed is not None else None

    async def list_runnable_jobs(
        self, *, job_type: str, user_id: str | None = None, limit: int
    ) -> list[str]:
        """실행 가능한 대기·Lease 만료 Job ID를 시스템 Scope로 조회한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await set_system_job_scope(connection)
                return await list_runnable_agent_jobs(
                    connection,
                    job_type=job_type,
                    user_id=user_id,
                    limit=limit,
                )

    async def save_fetched_url(
        self,
        *,
        job: ClaimedJobRecord,
        title: str,
        markdown: str,
        resolved_url: str,
        published_at: datetime | None,
    ) -> dict[str, object]:
        """Jina 결과를 원본 Version으로 저장하고 후속 Wiki Job을 등록한다."""
        source_document_id = str(job.payload.get("source_document_id") or "")
        source_event_id = str(job.payload.get("source_event_id") or "")
        source_event_row_id = str(job.payload.get("source_event_row_id") or "")
        if not source_document_id or not source_event_id or not source_event_row_id:
            raise ValueError("URL 수집 Job Payload에 원본 식별자가 없습니다.")
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await set_personal_wiki_scope(connection, user_id=job.user_id)
                saved = await save_user_url_document_version(
                    connection,
                    user_id=job.user_id,
                    source_document_id=source_document_id,
                    source_event_row_id=source_event_row_id,
                    title=title,
                    raw_content=markdown,
                    resolved_url=resolved_url,
                    published_at=published_at,
                )
                if saved is None:
                    await mark_url_source_event(
                        connection,
                        source_event_row_id=source_event_row_id,
                        status="completed",
                    )
                    return {
                        "source_document_id": source_document_id,
                        "unchanged": True,
                    }
                enqueued = await enqueue_personal_wiki_build_job(
                    connection,
                    user_id=job.user_id,
                    source_document_id=source_document_id,
                    source_document_version_id=saved.source_version_id,
                    source_version=saved.version,
                    source_event_id=source_event_id,
                    source_event_row_id=source_event_row_id,
                    feature_id="SVC-003",
                )
        return {
            "source_document_id": source_document_id,
            "source_document_version_id": saved.source_version_id,
            "source_version": saved.version,
            "wiki_build_job_id": enqueued.job_id,
            "unchanged": False,
        }

    async def build_personal_wiki(
        self, *, job: ClaimedJobRecord, model: str
    ) -> dict[str, object]:
        """점유한 Job Payload의 원본 Version으로 증분 Wiki Build를 실행한다."""
        source_version_id = str(
            job.payload.get("source_document_version_id") or ""
        )
        if not source_version_id:
            raise ValueError("Wiki Build Job Payload에 원본 Version ID가 없습니다.")
        async with self._pool.connection() as connection:
            persisted, plan = await build_incremental_wiki(
                connection,
                user_id=job.user_id,
                source_document_version_id=source_version_id,
                job_id=job.job_id,
                model=model,
            )
        return {
            "wiki_version_id": persisted.wiki_version_id,
            "wiki_version": persisted.wiki_version,
            "chunk_count": persisted.chunk_count,
            "affected_documents": [
                {
                    "document_id": document.document_id,
                    "document_version_id": document.document_version_id,
                    "document_kind": document.document_kind,
                    "document_key": document.document_key,
                    "file_path": document.file_path,
                    "version": document.version,
                    "action": document.action,
                }
                for document in persisted.affected_documents
            ],
            "artifacts": {
                "index": plan.index.content,
                "source": plan.source_manifest.content,
                "log": plan.log_entry.content,
            },
        }

    async def build_bambi_content(
        self, *, job: ClaimedJobRecord, model: str
    ) -> dict[str, object]:
        """개인·Global 문서를 검색해 Bambi 콘텐츠를 생성하고 영속화한다."""
        topic = str(job.payload.get("topic") or "").strip()
        content_type = str(job.payload.get("content_type") or "").strip()
        language = str(job.payload.get("language") or "ko").strip()
        if not topic or not content_type:
            raise ValueError("Bambi Job Payload에 topic과 content_type이 필요합니다.")
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await set_personal_wiki_scope(connection, user_id=job.user_id)
                contexts = await load_bambi_context(
                    connection,
                    user_id=job.user_id,
                    query=topic,
                )
        started = monotonic()
        generated = await asyncio.to_thread(
            generate_bambi_content,
            topic=topic,
            content_type=content_type,
            language=language,
            contexts=contexts,
            model=model,
        )
        latency_ms = int((monotonic() - started) * 1000)
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await set_personal_wiki_scope(connection, user_id=job.user_id)
                return await persist_bambi_generation(
                    connection,
                    job_id=job.job_id,
                    user_id=job.user_id,
                    attempt_number=job.attempt_number,
                    content_type=content_type,
                    generated=generated,
                    contexts=contexts,
                    latency_ms=latency_ms,
                )

    async def complete_job(
        self,
        *,
        job: ClaimedJobRecord,
        worker_id: str,
        result: dict[str, object],
    ) -> None:
        """Lease 소유권을 확인하고 Job과 Attempt를 완료 처리한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await set_system_job_scope(connection)
                await complete_agent_job(
                    connection,
                    job=self._to_claimed_job(job),
                    worker_id=worker_id,
                    result=result,
                )

    async def fail_job(
        self,
        *,
        job: ClaimedJobRecord,
        worker_id: str,
        error_code: str,
        error_message: str,
        retryable: bool,
    ) -> str:
        """Lease 소유권을 확인하고 Job 실패 또는 재시도를 기록한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await set_system_job_scope(connection)
                return await fail_agent_job(
                    connection,
                    job=self._to_claimed_job(job),
                    worker_id=worker_id,
                    error_code=error_code,
                    error_message=error_message,
                    retryable=retryable,
                )

    async def list_generated_contents(
        self,
        user_id: str,
        *,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        """사용자의 Bambi 생성 후보를 최신순으로 조회한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await set_personal_wiki_scope(connection, user_id=user_id)
                count_cursor = await connection.execute(
                    "SELECT COUNT(*) AS total FROM agent.generated_content_candidates WHERE user_id = %s",
                    (user_id,),
                )
                count = await count_cursor.fetchone()
                cursor = await connection.execute(
                    """
                    SELECT
                        id AS candidate_id,
                        content_id,
                        version,
                        content_type,
                        status,
                        title,
                        summary,
                        created_at
                    FROM agent.generated_content_candidates
                    WHERE user_id = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (user_id, limit, offset),
                )
                rows = await cursor.fetchall()
        return {
            "user_id": user_id,
            "total": int(count["total"]),
            "items": [
                {**dict(row), "candidate_id": str(row["candidate_id"])}
                for row in rows
            ],
        }

    async def get_generated_content(
        self, user_id: str, candidate_id: str
    ) -> dict[str, object] | None:
        """사용자의 생성 콘텐츠 본문, 실행 정보와 Citation을 조회한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await set_personal_wiki_scope(connection, user_id=user_id)
                cursor = await connection.execute(
                    """
                    SELECT
                        candidate.id AS candidate_id,
                        candidate.content_id,
                        candidate.version,
                        candidate.content_type,
                        candidate.status,
                        candidate.title,
                        candidate.summary,
                        candidate.body,
                        candidate.structured_body,
                        candidate.snapshot_hash,
                        candidate.created_at,
                        candidate.generation_request_id,
                        candidate.generation_run_id,
                        run.latency_ms
                    FROM agent.generated_content_candidates AS candidate
                    JOIN agent.generation_runs AS run
                      ON run.id = candidate.generation_run_id
                    WHERE candidate.id = %s AND candidate.user_id = %s
                    """,
                    (candidate_id, user_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                citation_cursor = await connection.execute(
                    """
                    SELECT
                        id AS citation_id,
                        ordinal,
                        document_version_id,
                        chunk_id,
                        title,
                        url,
                        quoted_text,
                        claim_paths[1] AS reference
                    FROM agent.citations
                    WHERE candidate_id = %s AND user_id = %s
                    ORDER BY ordinal
                    """,
                    (candidate_id, user_id),
                )
                citations = await citation_cursor.fetchall()
        return {
            **dict(row),
            "candidate_id": str(row["candidate_id"]),
            "generation_request_id": str(row["generation_request_id"]),
            "generation_run_id": str(row["generation_run_id"]),
            "structured_body": dict(row["structured_body"] or {}),
            "user_id": user_id,
            "citations": [
                {
                    **dict(citation),
                    "citation_id": str(citation["citation_id"]),
                    "document_version_id": (
                        str(citation["document_version_id"])
                        if citation["document_version_id"]
                        else None
                    ),
                    "chunk_id": (
                        str(citation["chunk_id"]) if citation["chunk_id"] else None
                    ),
                }
                for citation in citations
            ],
        }
