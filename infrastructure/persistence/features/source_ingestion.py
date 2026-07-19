"""사용자 클리핑·URL 원본과 Agent Job을 함께 저장한다.

Service API가 성공을 반환하기 전에 Source Event, 원본 문서·Version과 후속
Job을 한 트랜잭션에서 멱등 저장할 수 있는 PostgreSQL 함수를 제공한다.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from agent.wiki_builder.features.vault import compute_content_hash
from infrastructure.persistence.features.jobs import (
    enqueue_personal_wiki_build_job,
    enqueue_url_collection_job,
)
from infrastructure.persistence.features.personal_wiki import register_user_url_source

type DictRow = dict[str, Any]


@dataclass(frozen=True, slots=True)
class PersistedSourceSubmission:
    """원본 저장과 후속 Job 등록을 완료한 결과."""

    source_document_id: str
    source_document_version_id: str | None
    source_version: int | None
    source_event_row_id: str
    job_id: str
    job_created: bool


def _event_payload(
    *,
    title: str | None = None,
    author: str | None = None,
    published_at: datetime | None = None,
    clipped_on: date | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    memo: str | None = None,
) -> dict[str, object]:
    """원문 본문을 중복하지 않는 Source Event Metadata를 만든다."""
    return {
        key: value
        for key, value in {
            "title": title,
            "author": author,
            "published": published_at.isoformat() if published_at else None,
            "created": clipped_on.isoformat() if clipped_on else None,
            "description": description,
            "tags": tags or [],
            "memo": memo,
            "content_format": "markdown",
        }.items()
        if value is not None and value != ""
    }


async def save_web_clipping_and_enqueue(
    connection: AsyncConnection[DictRow],
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
) -> PersistedSourceSubmission:
    """클리핑 Markdown과 Wiki Build Job을 같은 트랜잭션에 멱등 저장한다."""
    namespace_key = f"user/{user_id}"
    content_hash = compute_content_hash(content)
    event_cursor = await connection.execute(
        """
        INSERT INTO agent.wiki_source_events (
            user_id,
            source_event_id,
            source_type,
            occurred_at,
            source_url,
            payload,
            status
        ) VALUES (
            %s, %s, 'web_clipping', COALESCE(%s, clock_timestamp()), %s, %s, 'received'
        )
        ON CONFLICT (user_id, source_event_id) DO UPDATE SET
            source_url = EXCLUDED.source_url,
            payload = EXCLUDED.payload,
            status = CASE
                WHEN agent.wiki_source_events.status = 'completed' THEN 'completed'
                ELSE 'received'
            END,
            error_code = NULL,
            error_message = NULL,
            updated_at = clock_timestamp()
        RETURNING id
        """,
        (
            user_id,
            source_event_id,
            occurred_at,
            source_url,
            Jsonb(
                _event_payload(
                    title=title,
                    author=author,
                    published_at=published_at,
                    clipped_on=clipped_on,
                    description=description,
                    tags=tags,
                    memo=memo,
                )
            ),
        ),
    )
    event_row = await event_cursor.fetchone()
    source_event_row_id = str(event_row["id"])

    head_cursor = await connection.execute(
        """
        SELECT id
        FROM agent.user_source_documents
        WHERE namespace_key = %s
          AND deleted_at IS NULL
          AND (canonical_url = %s OR content_hash = %s)
        ORDER BY (canonical_url = %s) DESC, updated_at DESC
        LIMIT 1
        FOR UPDATE
        """,
        (namespace_key, source_url, content_hash, source_url),
    )
    head = await head_cursor.fetchone()
    if head is None:
        insert_cursor = await connection.execute(
            """
            INSERT INTO agent.user_source_documents (
                user_id,
                namespace_key,
                source_type,
                canonical_url,
                current_version,
                content_hash,
                metadata
            ) VALUES (%s, %s, 'web_clipping', %s, 1, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (
                user_id,
                namespace_key,
                source_url,
                content_hash,
                Jsonb({"ingested_by": "web-clipper"}),
            ),
        )
        head = await insert_cursor.fetchone()
        if head is None:
            retry_cursor = await connection.execute(
                """
                SELECT id
                FROM agent.user_source_documents
                WHERE namespace_key = %s
                  AND deleted_at IS NULL
                  AND (canonical_url = %s OR content_hash = %s)
                ORDER BY (canonical_url = %s) DESC, updated_at DESC
                LIMIT 1
                FOR UPDATE
                """,
                (namespace_key, source_url, content_hash, source_url),
            )
            head = await retry_cursor.fetchone()
            if head is None:
                raise RuntimeError("웹 클리핑 원본 문서 Head를 저장하지 못했습니다.")
    source_document_id = str(head["id"])

    version_cursor = await connection.execute(
        """
        SELECT id, version, content_hash
        FROM agent.user_source_document_versions
        WHERE source_document_id = %s
        ORDER BY version DESC
        LIMIT 1
        FOR UPDATE
        """,
        (source_document_id,),
    )
    latest = await version_cursor.fetchone()
    if latest is not None and latest["content_hash"] == content_hash:
        source_document_version_id = str(latest["id"])
        source_version = int(latest["version"])
    else:
        source_version = int(latest["version"]) + 1 if latest else 1
        saved_cursor = await connection.execute(
            """
            INSERT INTO agent.user_source_document_versions (
                source_document_id,
                namespace_key,
                source_event_id,
                version,
                title,
                author,
                published_at,
                clipped_on,
                description,
                tags,
                raw_content,
                content_format,
                content_hash,
                source_metadata
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, CURRENT_DATE),
                %s, %s, %s, 'markdown', %s, %s
            )
            RETURNING id
            """,
            (
                source_document_id,
                namespace_key,
                source_event_row_id,
                source_version,
                title,
                author,
                published_at,
                clipped_on,
                description,
                tags,
                content,
                content_hash,
                Jsonb({"clipper": "obsidian-web-clipper"}),
            ),
        )
        saved = await saved_cursor.fetchone()
        source_document_version_id = str(saved["id"])
        await connection.execute(
            """
            UPDATE agent.user_source_documents
            SET
                current_version = %s,
                content_hash = %s,
                updated_at = clock_timestamp()
            WHERE id = %s
            """,
            (source_version, content_hash, source_document_id),
        )

    enqueued = await enqueue_personal_wiki_build_job(
        connection,
        user_id=user_id,
        source_document_id=source_document_id,
        source_document_version_id=source_document_version_id,
        source_version=source_version,
        source_event_id=source_event_id,
        source_event_row_id=source_event_row_id,
        feature_id="SVC-002",
        request_id=request_id,
    )
    return PersistedSourceSubmission(
        source_document_id=source_document_id,
        source_document_version_id=source_document_version_id,
        source_version=source_version,
        source_event_row_id=source_event_row_id,
        job_id=enqueued.job_id,
        job_created=enqueued.created,
    )


async def register_url_and_enqueue(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_event_id: str,
    url: str,
    occurred_at: datetime | None,
    memo: str | None,
    request_id: str,
) -> PersistedSourceSubmission:
    """URL 원본 Head와 비동기 수집 Job을 같은 트랜잭션에 등록한다."""
    registered = await register_user_url_source(
        connection,
        user_id=user_id,
        url=url,
        source_event_id=source_event_id,
    )
    await connection.execute(
        """
        UPDATE agent.wiki_source_events
        SET occurred_at = COALESCE(%s, occurred_at, clock_timestamp()),
            payload = %s,
            updated_at = clock_timestamp()
        WHERE id = %s
        """,
        (
            occurred_at,
            Jsonb({"url": url, **({"memo": memo} if memo else {})}),
            registered.source_event_row_id,
        ),
    )
    enqueued = await enqueue_url_collection_job(
        connection,
        user_id=user_id,
        source_document_id=registered.source_document_id,
        source_event_id=source_event_id,
        source_event_row_id=registered.source_event_row_id,
        url=url,
        request_id=request_id,
    )
    return PersistedSourceSubmission(
        source_document_id=registered.source_document_id,
        source_document_version_id=None,
        source_version=registered.latest_version,
        source_event_row_id=registered.source_event_row_id,
        job_id=enqueued.job_id,
        job_created=enqueued.created,
    )
