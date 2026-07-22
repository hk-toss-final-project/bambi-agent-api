"""사용자 Context, Report Builder Job·검색 Context와 생성 결과 영속화.

Service API의 생성 요청을 PostgreSQL Job으로 등록하고, Report Builder Worker가 개인
Wiki와 Global 문서를 검색해 만든 콘텐츠·Citation·Publish Snapshot을 저장한다.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from shared.report_models import ReportContextDocument, GeneratedReportContent

type DictRow = dict[str, Any]


class StaleContextVersionError(RuntimeError):
    """저장된 사용자 Context보다 오래되거나 같은 Version 요청 오류."""


class UserContextRequiredError(RuntimeError):
    """Report Builder 생성에 필요한 사용자 Context가 없는 오류."""


@dataclass(frozen=True, slots=True)
class StoredUserContext:
    """PostgreSQL에 저장된 사용자 Context Snapshot."""

    context_id: str
    user_id: str
    context_version: int
    plan: str
    preferred_language: str
    personalization_enabled: bool
    blocked_interest_ids: list[str]
    blocked_source_ids: list[str]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PersistedGenerationSubmission:
    """Report Builder Generation Job과 생성 요청 저장 결과."""

    job_id: str
    generation_request_id: str


async def upsert_user_context_snapshot(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    context_version: int,
    plan: str,
    preferred_language: str,
    personalization_enabled: bool,
    blocked_interest_ids: Sequence[str],
    blocked_source_ids: Sequence[str],
) -> StoredUserContext:
    """새로운 사용자 Context Version만 append-only Snapshot으로 저장한다."""
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"context/{user_id}",),
    )
    current_cursor = await connection.execute(
        """
        SELECT context_version
        FROM agent.user_context_snapshots
        WHERE user_id = %s AND deleted_at IS NULL
        ORDER BY context_version DESC
        LIMIT 1
        """,
        (user_id,),
    )
    current = await current_cursor.fetchone()
    if current is not None and context_version <= int(current["context_version"]):
        raise StaleContextVersionError(user_id)
    checksum_payload = {
        "context_version": context_version,
        "plan": plan,
        "preferred_language": preferred_language,
        "personalization_enabled": personalization_enabled,
        "blocked_interest_ids": list(blocked_interest_ids),
        "blocked_source_ids": list(blocked_source_ids),
    }
    checksum = hashlib.sha256(
        json.dumps(checksum_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    cursor = await connection.execute(
        """
        INSERT INTO agent.user_context_snapshots (
            user_id,
            context_version,
            plan,
            preferred_language,
            personalization_enabled,
            blocked_interest_ids,
            blocked_source_ids,
            checksum
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, created_at
        """,
        (
            user_id,
            context_version,
            plan,
            preferred_language,
            personalization_enabled,
            list(blocked_interest_ids),
            list(blocked_source_ids),
            checksum,
        ),
    )
    row = await cursor.fetchone()
    return StoredUserContext(
        context_id=str(row["id"]),
        user_id=user_id,
        context_version=context_version,
        plan=plan,
        preferred_language=preferred_language,
        personalization_enabled=personalization_enabled,
        blocked_interest_ids=list(blocked_interest_ids),
        blocked_source_ids=list(blocked_source_ids),
        created_at=row["created_at"],
    )


async def enqueue_report_generation_job(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    idempotency_key: str,
    topic: str,
    content_type: str,
    language: str | None,
    scheduled_at: datetime | None = None,
    request_id: str,
) -> PersistedGenerationSubmission:
    """최신 사용자 Context에 연결된 Report Builder Job과 생성 요청을 멱등 등록한다.

    scheduled_at을 지정하면 Worker Batch Claim의 `scheduled_at <= now`
    조건에 따라 그 시각 전에는 실행되지 않는 예약 Job으로 등록한다.
    같은 idempotency_key 재등록은 기존 Job을 재사용하며 예약 시각을
    변경하지 않는다.
    """
    context_cursor = await connection.execute(
        """
        SELECT id, plan, preferred_language
        FROM agent.user_context_snapshots
        WHERE user_id = %s AND deleted_at IS NULL
        ORDER BY context_version DESC
        LIMIT 1
        """,
        (user_id,),
    )
    context = await context_cursor.fetchone()
    if context is None:
        raise UserContextRequiredError(user_id)
    resolved_language = language or context["preferred_language"]
    job_payload = {
        "topic": topic,
        "content_type": content_type,
        "language": resolved_language,
    }
    job_cursor = await connection.execute(
        """
        INSERT INTO agent.agent_jobs (
            feature_id,
            job_type,
            user_id,
            idempotency_key,
            status,
            progress,
            payload,
            retryable,
            request_id,
            scheduled_at
        ) VALUES (
            'SVC-008', 'report_generation', %s, %s, 'queued', 0, %s, true, %s,
            COALESCE(%s, clock_timestamp())
        )
        ON CONFLICT (feature_id, COALESCE(user_id, ''), idempotency_key)
        DO NOTHING
        RETURNING id
        """,
        (user_id, idempotency_key, Jsonb(job_payload), request_id, scheduled_at),
    )
    job = await job_cursor.fetchone()
    if job is None:
        existing_cursor = await connection.execute(
            """
            SELECT id
            FROM agent.agent_jobs
            WHERE feature_id = 'SVC-008'
              AND COALESCE(user_id, '') = %s
              AND idempotency_key = %s
            """,
            (user_id, idempotency_key),
        )
        job = await existing_cursor.fetchone()
        if job is None:
            raise RuntimeError(f"멱등 충돌한 Report Builder Job을 찾을 수 없습니다: {idempotency_key}")
    request_cursor = await connection.execute(
        """
        INSERT INTO agent.generation_requests (
            job_id,
            user_id,
            user_context_snapshot_id,
            topic,
            content_type,
            plan,
            language,
            status,
            parameters
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s)
        ON CONFLICT (job_id) DO NOTHING
        RETURNING id
        """,
        (
            job["id"],
            user_id,
            context["id"],
            topic,
            content_type,
            context["plan"],
            resolved_language,
            Jsonb({"retrieval": "personal-global-keyword-v1"}),
        ),
    )
    generation_request = await request_cursor.fetchone()
    if generation_request is None:
        existing_request_cursor = await connection.execute(
            "SELECT id FROM agent.generation_requests WHERE job_id = %s",
            (job["id"],),
        )
        generation_request = await existing_request_cursor.fetchone()
    return PersistedGenerationSubmission(
        job_id=str(job["id"]),
        generation_request_id=str(generation_request["id"]),
    )


async def load_report_context(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    query: str,
    top_k_per_scope: int = 5,
) -> list[ReportContextDocument]:
    """개인 Wiki와 Global 최신 문서의 Keyword·Trigram 검색 Context를 조회한다."""
    if not 1 <= top_k_per_scope <= 20:
        raise ValueError("Report Builder 검색 top_k는 1에서 20 사이여야 합니다.")
    namespace_key = f"user/{user_id}"
    cursor = await connection.execute(
        """
        WITH scored AS (
            SELECT
                version.id AS document_version_id,
                chunk.id AS chunk_id,
                document.namespace_key,
                version.title,
                chunk.content,
                COALESCE(document.canonical_url, version.source_metadata->>'url') AS url,
                GREATEST(
                    similarity(chunk.content, %s),
                    ts_rank(chunk.search_vector, plainto_tsquery('simple', %s))
                ) + CASE WHEN document.namespace_key = %s THEN 0.05 ELSE 0 END AS score
            FROM agent.wiki_chunks AS chunk
            JOIN agent.wiki_document_versions AS version
              ON version.id = chunk.document_version_id
             AND version.namespace_key = chunk.namespace_key
            JOIN agent.wiki_documents AS document
              ON document.id = version.document_id
             AND document.namespace_key = version.namespace_key
             AND document.current_version = version.version
            WHERE chunk.namespace_key IN (%s, 'global')
              AND chunk.is_searchable
              AND document.deleted_at IS NULL
              AND (
                    similarity(chunk.content, %s) > 0.05
                    OR chunk.search_vector @@ plainto_tsquery('simple', %s)
              )
        ), ranked AS (
            SELECT *, row_number() OVER (
                PARTITION BY namespace_key = 'global'
                ORDER BY score DESC, document_version_id, chunk_id
            ) AS scope_rank
            FROM scored
        )
        SELECT *
        FROM ranked
        WHERE scope_rank <= %s
        ORDER BY (namespace_key = 'global'), score DESC
        """,
        (query, query, namespace_key, namespace_key, query, query, top_k_per_scope),
    )
    rows = await cursor.fetchall()
    if not rows:
        fallback_cursor = await connection.execute(
            """
            WITH recent AS (
                SELECT
                    version.id AS document_version_id,
                    chunk.id AS chunk_id,
                    document.namespace_key,
                    version.title,
                    chunk.content,
                    COALESCE(document.canonical_url, version.source_metadata->>'url') AS url,
                    0::float AS score,
                    row_number() OVER (
                        PARTITION BY document.namespace_key = 'global'
                        ORDER BY document.updated_at DESC, chunk.chunk_index
                    ) AS scope_rank
                FROM agent.wiki_chunks AS chunk
                JOIN agent.wiki_document_versions AS version
                  ON version.id = chunk.document_version_id
                 AND version.namespace_key = chunk.namespace_key
                JOIN agent.wiki_documents AS document
                  ON document.id = version.document_id
                 AND document.namespace_key = version.namespace_key
                 AND document.current_version = version.version
                WHERE chunk.namespace_key IN (%s, 'global')
                  AND chunk.is_searchable
                  AND document.deleted_at IS NULL
            )
            SELECT * FROM recent
            WHERE scope_rank <= %s
            ORDER BY (namespace_key = 'global'), scope_rank
            """,
            (namespace_key, top_k_per_scope),
        )
        rows = await fallback_cursor.fetchall()
    personal_index = 0
    global_index = 0
    contexts: list[ReportContextDocument] = []
    for row in rows:
        if row["namespace_key"] == "global":
            global_index += 1
            reference = f"G{global_index}"
        else:
            personal_index += 1
            reference = f"P{personal_index}"
        contexts.append(
            ReportContextDocument(
                reference=reference,
                document_version_id=str(row["document_version_id"]),
                chunk_id=str(row["chunk_id"]),
                namespace_key=row["namespace_key"],
                title=row["title"],
                content=row["content"],
                url=row["url"],
                score=float(row["score"]),
            )
        )
    return contexts


async def persist_report_generation(
    connection: AsyncConnection[DictRow],
    *,
    job_id: str,
    user_id: str,
    attempt_number: int,
    content_type: str,
    generated: GeneratedReportContent,
    contexts: Sequence[ReportContextDocument],
    latency_ms: int,
) -> dict[str, object]:
    """생성 Run·후보·Citation·Publish Snapshot·Outbox를 한 트랜잭션에 저장한다."""
    request_cursor = await connection.execute(
        """
        SELECT id
        FROM agent.generation_requests
        WHERE job_id = %s AND user_id = %s
        FOR UPDATE
        """,
        (job_id, user_id),
    )
    generation_request = await request_cursor.fetchone()
    if generation_request is None:
        raise ValueError("Report Builder Job에 연결된 generation_request가 없습니다.")
    await connection.execute(
        "UPDATE agent.generation_requests SET status = 'running', updated_at = clock_timestamp() WHERE id = %s",
        (generation_request["id"],),
    )
    run_cursor = await connection.execute(
        """
        INSERT INTO agent.generation_runs (
            generation_request_id,
            user_id,
            attempt_number,
            status,
            latency_ms,
            run_metadata
        ) VALUES (%s, %s, %s, 'running', %s, %s)
        RETURNING id
        """,
        (
            generation_request["id"],
            user_id,
            attempt_number,
            latency_ms,
            Jsonb(
                {
                    "retrieval_references": [context.reference for context in contexts],
                    "retrieval_scores": {
                        context.reference: context.score for context in contexts
                    },
                }
            ),
        ),
    )
    generation_run = await run_cursor.fetchone()
    content_id = f"report-{job_id}"
    version_cursor = await connection.execute(
        """
        SELECT COALESCE(MAX(version), 0) + 1 AS next_version
        FROM agent.generated_content_candidates
        WHERE content_id = %s
        """,
        (content_id,),
    )
    version_row = await version_cursor.fetchone()
    content_version = int(version_row["next_version"])
    snapshot_hash = hashlib.sha256(
        f"{generated.title}\n{generated.summary}\n{generated.body}".encode("utf-8")
    ).hexdigest()
    await connection.execute(
        """
        UPDATE agent.generated_content_candidates
        SET status = 'superseded', updated_at = clock_timestamp()
        WHERE content_id = %s AND status IN ('draft', 'ready')
        """,
        (content_id,),
    )
    candidate_cursor = await connection.execute(
        """
        INSERT INTO agent.generated_content_candidates (
            generation_request_id,
            generation_run_id,
            user_id,
            content_id,
            version,
            content_type,
            status,
            title,
            summary,
            body,
            structured_body,
            snapshot_hash
        ) VALUES (%s, %s, %s, %s, %s, %s, 'ready', %s, %s, %s, %s, %s)
        RETURNING id, created_at
        """,
        (
            generation_request["id"],
            generation_run["id"],
            user_id,
            content_id,
            content_version,
            content_type,
            generated.title,
            generated.summary,
            generated.body,
            Jsonb({"format": "markdown"}),
            snapshot_hash,
        ),
    )
    candidate = await candidate_cursor.fetchone()
    contexts_by_reference = {context.reference: context for context in contexts}
    citation_payloads: list[dict[str, object]] = []
    for ordinal, reference in enumerate(generated.citation_references):
        context = contexts_by_reference[reference]
        citation_hash = hashlib.sha256(
            f"{candidate['id']}:{reference}:{context.chunk_id}".encode("utf-8")
        ).hexdigest()
        citation_cursor = await connection.execute(
            """
            INSERT INTO agent.citations (
                candidate_id,
                user_id,
                ordinal,
                document_version_id,
                chunk_id,
                title,
                url,
                quoted_text,
                claim_paths,
                citation_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                candidate["id"],
                user_id,
                ordinal,
                context.document_version_id,
                context.chunk_id,
                context.title,
                context.url,
                context.content[:500],
                [reference],
                citation_hash,
            ),
        )
        citation = await citation_cursor.fetchone()
        citation_payloads.append(
            {
                "citation_id": str(citation["id"]),
                "title": context.title,
                "url": context.url or "",
                "reference": reference,
            }
        )
    await connection.execute(
        """
        UPDATE agent.generation_runs
        SET status = 'completed', completed_at = clock_timestamp()
        WHERE id = %s
        """,
        (generation_run["id"],),
    )
    await connection.execute(
        """
        UPDATE agent.generation_requests
        SET status = 'completed', updated_at = clock_timestamp()
        WHERE id = %s
        """,
        (generation_request["id"],),
    )
    publish_payload = {
        "title": generated.title,
        "summary": generated.summary,
        "body": generated.body,
        "citations": citation_payloads,
    }
    await connection.execute(
        """
        INSERT INTO agent.publish_snapshots (
            candidate_id,
            user_id,
            content_id,
            version,
            snapshot_hash,
            payload,
            status,
            created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, 'ready', %s)
        """,
        (
            candidate["id"],
            user_id,
            content_id,
            content_version,
            snapshot_hash,
            Jsonb(publish_payload),
            candidate["created_at"],
        ),
    )
    await connection.execute(
        """
        INSERT INTO agent.event_outbox (
            aggregate_type,
            aggregate_id,
            event_type,
            deduplication_key,
            payload
        ) VALUES ('generated_content', %s, 'CONTENT_READY', %s, %s)
        ON CONFLICT (deduplication_key) DO NOTHING
        """,
        (
            content_id,
            f"content-ready:{content_id}:v{content_version}",
            Jsonb(
                {
                    "content_id": content_id,
                    "version": content_version,
                    "user_id": user_id,
                    "snapshot_hash": snapshot_hash,
                }
            ),
        ),
    )
    return {
        "generation_request_id": str(generation_request["id"]),
        "generation_run_id": str(generation_run["id"]),
        "content_candidate_id": str(candidate["id"]),
        "content_id": content_id,
        "version": content_version,
        "title": generated.title,
        "summary": generated.summary,
        "body": generated.body,
        "snapshot_hash": snapshot_hash,
        "citations": citation_payloads,
    }
