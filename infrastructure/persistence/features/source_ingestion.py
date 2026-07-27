"""사용자 클리핑·URL 원본과 Agent Job을 함께 저장한다.

Service API가 성공을 반환하기 전에 Source Event, 원본 문서·Version과 후속
Job을 한 트랜잭션에서 멱등 저장할 수 있는 PostgreSQL 함수를 제공한다.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from shared.hashing import compute_content_hash
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


class GeneratedContentNotFoundError(Exception):
    """위키마킹 대상 생성 콘텐츠를 찾을 수 없을 때 발생하는 저장소 오류."""

    def __init__(self, content_id: str) -> None:
        """찾지 못한 콘텐츠 식별자를 보관한다."""
        super().__init__(f"생성 콘텐츠를 찾을 수 없습니다: {content_id}")
        self.content_id = content_id


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


async def _upsert_user_source_version(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    namespace_key: str,
    source_type: str,
    canonical_url: str | None,
    source_event_row_id: str,
    title: str,
    author: str | None,
    published_at: datetime | None,
    clipped_on: date | None,
    description: str | None,
    tags: list[str],
    content: str,
    content_hash: str,
    head_metadata: dict[str, object],
    version_metadata: dict[str, object],
) -> tuple[str, str, int]:
    """원본 문서 Head와 내용 Version을 멱등 저장하고 식별자를 반환한다.

    같은 canonical_url 또는 content_hash의 Head를 재사용하고, 최신 Version과
    내용이 같으면 새 Version을 만들지 않는다. 클리핑(SVC-002)과 위키마킹
    (SVC-004)이 공유하는 공용 경로다.

    Returns:
        (source_document_id, source_document_version_id, source_version)
    """
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
        (namespace_key, canonical_url, content_hash, canonical_url),
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
            ) VALUES (%s, %s, %s, %s, 1, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (
                user_id,
                namespace_key,
                source_type,
                canonical_url,
                content_hash,
                Jsonb(head_metadata),
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
                (namespace_key, canonical_url, content_hash, canonical_url),
            )
            head = await retry_cursor.fetchone()
            if head is None:
                raise RuntimeError("원본 문서 Head를 저장하지 못했습니다.")
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
                Jsonb(version_metadata),
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
    return source_document_id, source_document_version_id, source_version


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

    (
        source_document_id,
        source_document_version_id,
        source_version,
    ) = await _upsert_user_source_version(
        connection,
        user_id=user_id,
        namespace_key=namespace_key,
        source_type="web_clipping",
        canonical_url=source_url,
        source_event_row_id=source_event_row_id,
        title=title,
        author=author,
        published_at=published_at,
        clipped_on=clipped_on,
        description=description,
        tags=tags,
        content=content,
        content_hash=content_hash,
        head_metadata={"ingested_by": "web-clipper"},
        version_metadata={"clipper": "obsidian-web-clipper"},
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


async def save_content_mark_and_enqueue(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_event_id: str,
    content_id: str,
    occurred_at: datetime | None,
    memo: str | None,
    request_id: str,
) -> PersistedSourceSubmission:
    """위키마킹한 생성 콘텐츠를 원본 Version으로 물질화하고 Build Job을 멱등 등록한다.

    REPORT-021(자동 Wiki 편입 금지)의 짝이다 — 이 함수는 사용자가 명시적으로
    선택한 콘텐츠(SVC-004)만 받는다. 생성 후보 본문을 `content_mark` 원본으로
    복사해 클리핑과 같은 Wiki Build 파이프라인을 태운다.

    Args:
        connection: agent-db 커넥션 (호출자가 트랜잭션을 소유)
        user_id: 마킹한 사용자 ID
        source_event_id: Service가 부여한 멱등 이벤트 ID
        content_id: 생성 후보 Row ID 또는 논리 content_id
        occurred_at: 사용자가 마킹한 시각
        memo: 마킹 시 남긴 메모
        request_id: 요청 추적 ID

    Raises:
        GeneratedContentNotFoundError: 해당 사용자의 생성 콘텐츠가 없는 경우
    """
    candidate_cursor = await connection.execute(
        """
        SELECT content_id, version, content_type, title, summary, body
        FROM agent.generated_content_candidates
        WHERE user_id = %s AND (id::text = %s OR content_id = %s)
        ORDER BY (id::text = %s) DESC, version DESC
        LIMIT 1
        """,
        (user_id, content_id, content_id, content_id),
    )
    candidate = await candidate_cursor.fetchone()
    if candidate is None:
        raise GeneratedContentNotFoundError(content_id)

    namespace_key = f"user/{user_id}"
    content = str(candidate["body"] or "")
    content_hash = compute_content_hash(content)
    event_cursor = await connection.execute(
        """
        INSERT INTO agent.wiki_source_events (
            user_id,
            source_event_id,
            source_type,
            occurred_at,
            source_content_id,
            payload,
            status
        ) VALUES (
            %s, %s, 'content_mark', COALESCE(%s, clock_timestamp()), %s, %s, 'received'
        )
        ON CONFLICT (user_id, source_event_id) DO UPDATE SET
            source_content_id = EXCLUDED.source_content_id,
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
            str(candidate["content_id"]),
            Jsonb(
                _event_payload(
                    title=str(candidate["title"] or ""),
                    description=str(candidate["summary"] or "") or None,
                    memo=memo,
                )
            ),
        ),
    )
    event_row = await event_cursor.fetchone()
    source_event_row_id = str(event_row["id"])

    (
        source_document_id,
        source_document_version_id,
        source_version,
    ) = await _upsert_user_source_version(
        connection,
        user_id=user_id,
        namespace_key=namespace_key,
        source_type="content_mark",
        canonical_url=None,
        source_event_row_id=source_event_row_id,
        title=str(candidate["title"] or ""),
        author=None,
        published_at=None,
        clipped_on=None,
        description=str(candidate["summary"] or "") or None,
        tags=[],
        content=content,
        content_hash=content_hash,
        head_metadata={"ingested_by": "content-mark"},
        version_metadata={
            "origin": "generated_content",
            "content_id": str(candidate["content_id"]),
            "content_version": int(candidate["version"]),
            "content_type": str(candidate["content_type"] or ""),
        },
    )

    enqueued = await enqueue_personal_wiki_build_job(
        connection,
        user_id=user_id,
        source_document_id=source_document_id,
        source_document_version_id=source_document_version_id,
        source_version=source_version,
        source_event_id=source_event_id,
        source_event_row_id=source_event_row_id,
        feature_id="SVC-004",
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


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def db_002(
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
    """[DB-002] Wiki Source Event와 웹 클리핑 원본을 저장한다."""
    return await save_web_clipping_and_enqueue(
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
