"""기능 구현 모듈.

DB-002, DB-003, DB-004, DB-005, DB-006, DB-007 기능의 실제 구현 위치를 제공한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from collections.abc import Sequence
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

# 하위 호환 재노출: 기존 persistence.api의 Chunk 유틸 import 경로를 유지한다.
from domain.personal_wiki.embeddings.api import chunk_wiki_markdown, pwe_001, pwe_002
from domain.personal_wiki.documents.api import pwiki_007, pwiki_008
from domain.personal_wiki.source_events.api import wse_013
from shared.contracts import FeatureRequest, FeatureResult
from shared.hashing import compute_content_hash
from shared.wiki_models import (
    ExistingWikiEntry,
    WikiBuildPlan,
    WikiDocumentPlan,
    WikiRelationPlan,
)

type DictRow = dict[str, Any]


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def db_003(
    connection: AsyncConnection[DictRow],
    *,
    source: UserSourceDocumentForAgent,
    plan: WikiBuildPlan,
    job_id: str,
) -> PersistedWikiBuild:
    """[DB-003] 개인 Wiki 문서 저장.

    사용자별 Wiki 문서와 버전을 저장한다.
    """
    return await persist_wiki_build(
        connection, source=source, plan=plan, job_id=job_id
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def db_004(
    connection: AsyncConnection[DictRow],
    *,
    document_version_id: object,
    namespace_key: str,
    chunks: Sequence[str],
) -> int:
    """[DB-004] 개인 Wiki Chunk 저장.

    개인 Wiki 검색용 Chunk를 저장한다.
    """
    for chunk_index, chunk in enumerate(chunks):
        await connection.execute(
            """
            INSERT INTO agent.wiki_chunks (
                document_version_id,
                namespace_key,
                chunk_index,
                content,
                metadata
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (document_version_id, chunk_index) DO UPDATE
            SET content = EXCLUDED.content, metadata = EXCLUDED.metadata
            """,
            (
                document_version_id,
                namespace_key,
                chunk_index,
                chunk,
                Jsonb({"policy": "markdown-heading-v1"}),
            ),
        )
    return len(chunks)


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def db_005(
    connection: AsyncConnection[DictRow],
    *,
    namespace_key: str,
    model_name: str,
    values: Sequence[WikiEmbeddingValue],
) -> int:
    """[DB-005] 개인 Wiki Embedding 저장.

    개인 Wiki의 Vector 데이터를 저장한다.
    """
    return await persist_wiki_embeddings(
        connection,
        namespace_key=namespace_key,
        model_name=model_name,
        values=values,
    )


async def db_006(request: FeatureRequest) -> FeatureResult:
    """[DB-006] 개인 Wiki Version 저장.

    개인 Wiki 재구성 버전을 저장한다.
    """
    raise NotImplementedError("[DB-006] 기능 구현이 필요합니다.")


async def db_007(request: FeatureRequest) -> FeatureResult:
    """[DB-007] 사용자 관심사 저장.

    관심사 프로필, 계층, 관계를 저장한다.
    """
    raise NotImplementedError("[DB-007] 기능 구현이 필요합니다.")


@dataclass(frozen=True, slots=True)
class UserSourceDocumentForAgent:
    """WBA-001/WBA-003이 그대로 읽어 쓸 수 있는 사용자 원본 문서 Version 데이터."""

    source_document_id: str
    source_document_version_id: str
    source_event_id: str | None
    user_id: str
    namespace_key: str
    source_type: str
    canonical_url: str | None
    version: int
    title: str
    author: str | None
    published_at: datetime | None
    clipped_on: date | None
    description: str | None
    tags: list[str] = field(default_factory=list)
    raw_content: str | None = None
    content_format: str = "markdown"
    content_hash: str = ""
    object_uri: str | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PersistedWikiDocument:
    """이번 Build에서 확정된 Wiki 문서 Version 하나."""

    document_id: str
    document_version_id: str
    document_kind: str
    document_key: str
    file_path: str
    version: int
    action: str


@dataclass(frozen=True, slots=True)
class PersistedWikiBuild:
    """DB 트랜잭션으로 저장된 개인 Wiki Build 결과."""

    wiki_version_id: str
    wiki_version: int
    affected_documents: list[PersistedWikiDocument]
    chunk_count: int


@dataclass(frozen=True, slots=True)
class WikiChunkForEmbedding:
    """Embedding Provider에 전달할 Wiki Chunk 하나."""

    chunk_id: str
    content: str


@dataclass(frozen=True, slots=True)
class WikiEmbeddingValue:
    """Wiki Chunk와 Provider가 만든 1536차원 Vector 하나."""

    chunk_id: str
    content: str
    embedding: list[float]


async def get_user_source_document_version_for_agent(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_document_version_id: str,
) -> UserSourceDocumentForAgent | None:
    """Personal Wiki Builder Agent가 읽을 사용자 원본 Version을 PostgreSQL에서 조회한다.

    user_source_document_versions의 Frontmatter·Markdown 원문과 user_source_documents의
    소유자·canonical_url을 한 Row로 결합해 반환한다. WBA-001이 Job에 담긴
    source_document_version_id로 이 Version만 증분 로드하고, WBA-003이 반환된 데이터를
    그대로 정규화 입력으로 사용한다. 호출 전 Connection Transaction에 RLS를 위한
    `app.user_id`, `app.access_scope`를 `SET LOCAL`로 지정해야 한다.
    """
    cursor = await connection.execute(
        """
        SELECT
            document.id AS source_document_id,
            document.user_id,
            document.namespace_key,
            document.source_type,
            document.canonical_url,
            version.id AS source_document_version_id,
            version.source_event_id,
            version.version,
            version.title,
            version.author,
            version.published_at,
            version.clipped_on,
            version.description,
            version.tags,
            version.raw_content,
            version.content_format,
            version.content_hash,
            version.object_uri,
            version.source_metadata
        FROM agent.user_source_document_versions AS version
        JOIN agent.user_source_documents AS document
          ON document.id = version.source_document_id
         AND document.namespace_key = version.namespace_key
        WHERE version.id = %s
          AND document.user_id = %s
          AND document.deleted_at IS NULL
        """,
        (source_document_version_id, user_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return UserSourceDocumentForAgent(
        source_document_id=str(row["source_document_id"]),
        source_document_version_id=str(row["source_document_version_id"]),
        source_event_id=(str(row["source_event_id"]) if row["source_event_id"] else None),
        user_id=row["user_id"],
        namespace_key=row["namespace_key"],
        source_type=row["source_type"],
        canonical_url=row["canonical_url"],
        version=row["version"],
        title=row["title"],
        author=row["author"],
        published_at=row["published_at"],
        clipped_on=row["clipped_on"],
        description=row["description"],
        tags=list(row["tags"] or []),
        raw_content=row["raw_content"],
        content_format=row["content_format"],
        content_hash=row["content_hash"],
        object_uri=row["object_uri"],
        source_metadata=dict(row["source_metadata"] or {}),
    )


async def set_personal_wiki_scope(
    connection: AsyncConnection[DictRow], *, user_id: str
) -> None:
    """현재 트랜잭션에 개인 Wiki RLS 사용자 Scope를 설정한다."""
    await connection.execute(
        "SELECT set_config('app.user_id', %s, true), "
        "set_config('app.access_scope', 'user', true)",
        (user_id,),
    )


@dataclass(frozen=True, slots=True)
class RegisteredUrlSource:
    """사용자 입력 URL을 수집 이벤트와 원본 문서로 등록한 결과."""

    source_event_row_id: str
    source_document_id: str
    latest_version: int | None
    latest_content_hash: str | None


@dataclass(frozen=True, slots=True)
class SavedUserSourceVersion:
    """내용 변경으로 새로 저장된 사용자 원본 문서 Version 하나."""

    source_version_id: str
    version: int
    content_hash: str


async def register_user_url_source(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    url: str,
    source_event_id: str,
) -> RegisteredUrlSource:
    """사용자가 입력한 URL을 수집 이벤트와 원본 문서 Head로 멱등 등록한다.

    URL은 문서의 지속적인 식별 정보이므로 user_source_documents.canonical_url에
    저장하고, 재수집 시 변할 수 있는 본문 스냅샷은 이후
    save_user_url_document_version이 user_source_document_versions에 저장한다.
    같은 user_id + source_event_id 재요청은 새 Row 없이 이벤트를 received로
    되돌리고, 같은 Namespace + URL 재등록은 기존 문서 Head를 재사용한다.

    Args:
        user_id: URL을 입력한 사용자 ID
        url: 입력된 원본 URL
        source_event_id: Service 계층이 부여한 멱등 이벤트 식별자

    Returns:
        이벤트 Row ID, 문서 ID와 비교 기준이 될 최신 Version·Hash
    """
    namespace_key = f"user/{user_id}"
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
        ) VALUES (%s, %s, 'url', clock_timestamp(), %s, %s, 'received')
        ON CONFLICT (user_id, source_event_id) DO UPDATE SET
            source_url = EXCLUDED.source_url,
            status = 'received',
            error_code = NULL,
            error_message = NULL,
            processed_at = NULL,
            updated_at = clock_timestamp()
        RETURNING id
        """,
        (user_id, source_event_id, url, Jsonb({"url": url})),
    )
    event_row = await event_cursor.fetchone()

    document_cursor = await connection.execute(
        """
        INSERT INTO agent.user_source_documents (
            user_id,
            namespace_key,
            source_type,
            canonical_url,
            content_hash,
            metadata
        ) VALUES (%s, %s, 'url', %s, %s, %s)
        ON CONFLICT (namespace_key, canonical_url)
        WHERE canonical_url IS NOT NULL AND deleted_at IS NULL
        DO UPDATE SET updated_at = clock_timestamp()
        RETURNING id
        """,
        (
            user_id,
            namespace_key,
            url,
            compute_content_hash(url),
            Jsonb({"registered_by": "user-url-ingestion"}),
        ),
    )
    document_row = await document_cursor.fetchone()

    latest_cursor = await connection.execute(
        """
        SELECT version, content_hash
        FROM agent.user_source_document_versions
        WHERE source_document_id = %s
        ORDER BY version DESC
        LIMIT 1
        """,
        (document_row["id"],),
    )
    latest = await latest_cursor.fetchone()
    return RegisteredUrlSource(
        source_event_row_id=str(event_row["id"]),
        source_document_id=str(document_row["id"]),
        latest_version=(int(latest["version"]) if latest else None),
        latest_content_hash=(latest["content_hash"] if latest else None),
    )


async def save_user_url_document_version(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_document_id: str,
    source_event_row_id: str | None,
    title: str,
    raw_content: str,
    resolved_url: str | None = None,
    published_at: datetime | None = None,
    description: str | None = None,
) -> SavedUserSourceVersion | None:
    """수집한 본문 스냅샷을 내용이 바뀐 경우에만 새 Version으로 저장한다.

    content_hash가 최신 Version과 같으면 새 Version을 만들지 않고 None을
    반환한다. 리다이렉트가 반영된 최종 URL은 수집 당시 근거를 남기기 위해
    source_metadata.resolved_url로 함께 보존한다.

    Args:
        user_id: 원본 문서 소유 사용자 ID
        source_document_id: user_source_documents Head ID
        source_event_row_id: 이 스냅샷을 만든 wiki_source_events Row ID
        title: 수집된 문서 제목
        raw_content: 정제된 Markdown 본문
        resolved_url: 리다이렉트된 최종 URL
        published_at: 원문 게시 시각
        description: 원문 요약 설명

    Returns:
        새로 저장된 Version 정보. 내용이 같아 저장을 생략하면 None
    """
    namespace_key = f"user/{user_id}"
    content_hash = compute_content_hash(raw_content)
    latest_cursor = await connection.execute(
        """
        SELECT version, content_hash
        FROM agent.user_source_document_versions
        WHERE source_document_id = %s
        ORDER BY version DESC
        LIMIT 1
        FOR UPDATE
        """,
        (source_document_id,),
    )
    latest = await latest_cursor.fetchone()
    if latest is not None and latest["content_hash"] == content_hash:
        return None
    next_version = (int(latest["version"]) + 1) if latest else 1

    source_metadata: dict[str, Any] = {"fetcher": "jina-reader"}
    if resolved_url is not None:
        source_metadata["resolved_url"] = resolved_url
    version_cursor = await connection.execute(
        """
        INSERT INTO agent.user_source_document_versions (
            source_document_id,
            namespace_key,
            source_event_id,
            version,
            title,
            published_at,
            clipped_on,
            description,
            raw_content,
            content_format,
            content_hash,
            source_metadata
        ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_DATE, %s, %s, 'markdown', %s, %s)
        RETURNING id
        """,
        (
            source_document_id,
            namespace_key,
            source_event_row_id,
            next_version,
            title,
            published_at,
            description,
            raw_content,
            content_hash,
            Jsonb(source_metadata),
        ),
    )
    version_row = await version_cursor.fetchone()
    await connection.execute(
        """
        UPDATE agent.user_source_documents
        SET
            current_version = %s,
            content_hash = %s,
            updated_at = clock_timestamp()
        WHERE id = %s
        """,
        (next_version, content_hash, source_document_id),
    )
    return SavedUserSourceVersion(
        source_version_id=str(version_row["id"]),
        version=next_version,
        content_hash=content_hash,
    )


async def mark_url_source_event(
    connection: AsyncConnection[DictRow],
    *,
    source_event_row_id: str,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """URL 수집 이벤트의 처리 상태를 갱신한다.

    실패한 수집은 문서 Version을 만들지 않고 이 이벤트 Row에 오류 코드와
    메시지로만 기록한다. completed·failed·ignored는 processed_at을 함께 남긴다.

    Args:
        source_event_row_id: wiki_source_events Row ID
        status: processing, completed, failed, ignored 중 하나
        error_code: 실패 원인 코드
        error_message: 실패 상세 메시지
    """
    status = await wse_013(status)
    await connection.execute(
        """
        UPDATE agent.wiki_source_events
        SET
            status = %s,
            error_code = %s,
            error_message = %s,
            retry_count = retry_count + CASE WHEN %s = 'failed' THEN 1 ELSE 0 END,
            processed_at = CASE
                WHEN %s IN ('completed', 'failed', 'ignored') THEN clock_timestamp()
                ELSE processed_at
            END,
            updated_at = clock_timestamp()
        WHERE id = %s
        """,
        (status, error_code, error_message, status, status, source_event_row_id),
    )


async def list_existing_wiki_entries(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    document_kind: str,
) -> list[ExistingWikiEntry]:
    """사용자 Namespace의 활성 entity 또는 concept 최신 Version을 조회한다."""
    if document_kind not in {"entity", "concept"}:
        raise ValueError(f"조회할 수 없는 Wiki 문서 유형입니다: {document_kind}")
    cursor = await connection.execute(
        """
        SELECT
            document.document_kind,
            document.document_key,
            document.domain,
            version.title,
            version.summary,
            version.source_metadata
        FROM agent.wiki_documents AS document
        JOIN agent.wiki_document_versions AS version
          ON version.document_id = document.id
         AND version.namespace_key = document.namespace_key
         AND version.version = document.current_version
        WHERE document.namespace_key = %s
          AND document.document_kind = %s
          AND document.deleted_at IS NULL
        ORDER BY document.document_key
        """,
        (f"user/{user_id}", document_kind),
    )
    rows = await cursor.fetchall()
    return [
        ExistingWikiEntry(
            document_kind=row["document_kind"],
            document_key=row["document_key"],
            title=row["title"],
            domain=row["domain"],
            summary=row["summary"],
            metadata=dict(row["source_metadata"] or {}),
        )
        for row in rows
    ]


async def list_existing_wiki_relations(
    connection: AsyncConnection[DictRow],
    *,
    namespace_key: str,
) -> list[WikiRelationPlan]:
    """Namespace에 누적된 활성 Wiki 문서 관계를 Build 계획 형식으로 조회한다."""
    cursor = await connection.execute(
        """
        SELECT
            source.document_kind AS source_document_kind,
            source.document_key AS source_document_key,
            target.document_kind AS target_document_kind,
            target.document_key AS target_document_key,
            relation.relation_type,
            relation.metadata
        FROM agent.wiki_document_relations AS relation
        JOIN agent.wiki_documents AS source
          ON source.id = relation.source_document_id
         AND source.namespace_key = relation.namespace_key
        JOIN agent.wiki_documents AS target
          ON target.id = relation.target_document_id
         AND target.namespace_key = relation.namespace_key
        WHERE relation.namespace_key = %s
          AND source.deleted_at IS NULL
          AND target.deleted_at IS NULL
        ORDER BY
            source.document_kind,
            source.document_key,
            target.document_kind,
            target.document_key,
            relation.relation_type
        """,
        (namespace_key,),
    )
    rows = await cursor.fetchall()
    return [
        WikiRelationPlan(
            source_document_key=row["source_document_key"],
            source_document_kind=row["source_document_kind"],
            target_document_key=row["target_document_key"],
            target_document_kind=row["target_document_kind"],
            relation_type=row["relation_type"],
            metadata=dict(row["metadata"] or {}),
        )
        for row in rows
    ]


class _ConnectionWikiChunkRepository:
    """현재 PostgreSQL 연결을 DB-004 Chunk 저장 경계로 노출한다."""

    def __init__(self, connection: AsyncConnection[DictRow]) -> None:
        """Chunk를 저장할 현재 Transaction 연결을 보관한다."""
        self._connection = connection

    async def save_chunks(
        self,
        *,
        document_version_id: object,
        namespace_key: str,
        chunks: Sequence[str],
    ) -> int:
        """DB-004를 통해 문서 Version의 Chunk를 저장한다."""
        return await db_004(
            self._connection,
            document_version_id=document_version_id,
            namespace_key=namespace_key,
            chunks=chunks,
        )


async def _upsert_wiki_document(
    connection: AsyncConnection[DictRow],
    *,
    source: UserSourceDocumentForAgent,
    document: WikiDocumentPlan,
    job_id: str,
) -> tuple[PersistedWikiDocument, bool]:
    """Wiki Head를 멱등 Upsert하고 내용이 바뀐 경우에만 새 Version을 추가한다.

    같은 Namespace에 동일 content_hash 문서가 이미 있으면(PWIKI-008 중복
    제거) 새 Head나 Version을 만들지 않고 기존 문서를 재사용해
    uq_wiki_documents_content 충돌을 방지한다.
    """
    content_hash = compute_content_hash(document.normalized_content)
    head_cursor = await connection.execute(
        """
        SELECT id, current_version, content_hash
        FROM agent.wiki_documents
        WHERE namespace_key = %s
          AND document_kind = %s
          AND document_key = %s
          AND deleted_at IS NULL
        FOR UPDATE
        """,
        (source.namespace_key, document.document_kind, document.document_key),
    )
    head = await head_cursor.fetchone()
    duplicate_cursor = await connection.execute(
        """
        SELECT id, document_kind, document_key, file_path, current_version
        FROM agent.wiki_documents
        WHERE namespace_key = %s
          AND content_hash = %s
          AND deleted_at IS NULL
        FOR UPDATE
        """,
        (source.namespace_key, content_hash),
    )
    duplicate = await pwiki_008(head, await duplicate_cursor.fetchone())

    persisted_kind = document.document_kind
    persisted_key = document.document_key
    persisted_path = document.file_path
    if head is None and duplicate is not None:
        # PWIKI-008: 동일 내용의 문서가 이미 있으면 새 Head 대신 재사용한다.
        document_id = duplicate["id"]
        version = int(duplicate["current_version"])
        changed = False
        action = "deduplicated"
        persisted_kind = duplicate["document_kind"]
        persisted_key = duplicate["document_key"]
        persisted_path = duplicate["file_path"]
    elif head is None:
        insert_cursor = await connection.execute(
            """
            INSERT INTO agent.wiki_documents (
                knowledge_scope,
                namespace_key,
                user_id,
                source_event_id,
                source_type,
                language,
                current_version,
                content_hash,
                metadata,
                document_kind,
                document_key,
                file_path,
                domain
            ) VALUES (
                'personal', %s, %s, %s, %s, 'und', 1, %s, %s, %s, %s, %s, %s
            )
            RETURNING id
            """,
            (
                source.namespace_key,
                source.user_id,
                source.source_event_id,
                source.source_type,
                content_hash,
                Jsonb({"builder": "personal-knowledge-wiki"}),
                document.document_kind,
                document.document_key,
                document.file_path,
                document.domain,
            ),
        )
        inserted = await insert_cursor.fetchone()
        document_id = inserted["id"]
        version = 1
        changed = True
        action = "create"
    else:
        document_id = head["id"]
        version = int(head["current_version"])
        changed = head["content_hash"] != content_hash
        action = "update" if changed else "unchanged"
        if changed and duplicate is not None:
            # 갱신 내용이 다른 문서와 동일하면 Version을 만들지 않는다(PWIKI-008).
            changed = False
            action = "deduplicated"
        if changed:
            version += 1
            await connection.execute(
                """
                UPDATE agent.wiki_documents
                SET
                    source_event_id = %s,
                    source_type = %s,
                    current_version = %s,
                    content_hash = %s,
                    file_path = %s,
                    domain = %s,
                    updated_at = clock_timestamp()
                WHERE id = %s
                """,
                (
                    source.source_event_id,
                    source.source_type,
                    version,
                    content_hash,
                    document.file_path,
                    document.domain,
                    document_id,
                ),
            )

    if changed:
        version_cursor = await connection.execute(
            """
            INSERT INTO agent.wiki_document_versions (
                document_id,
                namespace_key,
                version,
                title,
                summary,
                normalized_content,
                content_hash,
                source_metadata,
                created_by_job_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                document_id,
                source.namespace_key,
                version,
                document.title,
                document.summary,
                document.normalized_content,
                content_hash,
                Jsonb(document.metadata),
                job_id,
            ),
        )
        version_row = await version_cursor.fetchone()
        document_version_id = version_row["id"]
        chunks = await pwe_001(document.normalized_content)
        await pwe_002(
            _ConnectionWikiChunkRepository(connection),
            document_version_id=document_version_id,
            namespace_key=source.namespace_key,
            chunks=chunks,
        )
    else:
        version_cursor = await connection.execute(
            """
            SELECT id
            FROM agent.wiki_document_versions
            WHERE document_id = %s AND version = %s
            """,
            (document_id, version),
        )
        version_row = await version_cursor.fetchone()
        document_version_id = version_row["id"]

    await pwiki_007(
        connection,
        wiki_document_version_id=document_version_id,
        source_document_version_id=source.source_document_version_id,
        namespace_key=source.namespace_key,
    )
    return (
        PersistedWikiDocument(
            document_id=str(document_id),
            document_version_id=str(document_version_id),
            document_kind=persisted_kind,
            document_key=persisted_key,
            file_path=persisted_path,
            version=version,
            action=action,
        ),
        changed,
    )


async def persist_wiki_build(
    connection: AsyncConnection[DictRow],
    *,
    source: UserSourceDocumentForAgent,
    plan: WikiBuildPlan,
    job_id: str,
) -> PersistedWikiBuild:
    """Wiki Build 계획을 문서·출처·관계·Chunk·Snapshot으로 영속화한다."""
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (source.namespace_key,),
    )
    persisted: list[PersistedWikiDocument] = []
    changed_count = 0
    for document in [*plan.entities, *plan.concepts, plan.schema]:
        saved, changed = await _upsert_wiki_document(
            connection,
            source=source,
            document=document,
            job_id=job_id,
        )
        persisted.append(saved)
        changed_count += int(changed)

    document_cursor = await connection.execute(
        """
        SELECT id, document_kind, document_key
        FROM agent.wiki_documents
        WHERE namespace_key = %s AND deleted_at IS NULL
        """,
        (source.namespace_key,),
    )
    document_rows = await document_cursor.fetchall()
    ids = {
        (row["document_kind"], row["document_key"]): row["id"]
        for row in document_rows
    }
    for relation in plan.relations:
        source_id = ids.get(
            (relation.source_document_kind, relation.source_document_key)
        )
        target_id = ids.get(
            (relation.target_document_kind, relation.target_document_key)
        )
        if source_id is None or target_id is None or source_id == target_id:
            continue
        await connection.execute(
            """
            INSERT INTO agent.wiki_document_relations (
                source_document_id,
                target_document_id,
                namespace_key,
                relation_type,
                metadata
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source_document_id, target_document_id, relation_type)
            DO UPDATE SET metadata = EXCLUDED.metadata
            """,
            (
                source_id,
                target_id,
                source.namespace_key,
                relation.relation_type,
                Jsonb(relation.metadata),
            ),
        )

    existing_build_cursor = await connection.execute(
        """
        SELECT id, version
        FROM agent.wiki_versions
        WHERE user_id = %s AND built_by_job_id = %s
        ORDER BY version
        LIMIT 1
        FOR UPDATE
        """,
        (source.user_id, job_id),
    )
    existing_build = await existing_build_cursor.fetchone()
    if existing_build is None:
        version_cursor = await connection.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1 AS next_version
            FROM agent.wiki_versions
            WHERE user_id = %s
            """,
            (source.user_id,),
        )
        version_row = await version_cursor.fetchone()
        wiki_version = int(version_row["next_version"])
        build_cursor = await connection.execute(
            """
            INSERT INTO agent.wiki_versions (
                user_id,
                namespace_key,
                version,
                status,
                change_summary,
                built_by_job_id
            ) VALUES (%s, %s, %s, 'building', %s, %s)
            RETURNING id
            """,
            (
                source.user_id,
                source.namespace_key,
                wiki_version,
                Jsonb({"affected": len(persisted), "changed": changed_count}),
                job_id,
            ),
        )
        build_row = await build_cursor.fetchone()
        wiki_version_id = build_row["id"]
    else:
        wiki_version_id = existing_build["id"]
        wiki_version = int(existing_build["version"])
    await connection.execute(
        """
        INSERT INTO agent.wiki_version_documents (
            wiki_version_id,
            document_version_id,
            namespace_key,
            file_path
        )
        SELECT %s, version.id, document.namespace_key, document.file_path
        FROM agent.wiki_documents AS document
        JOIN agent.wiki_document_versions AS version
          ON version.document_id = document.id
         AND version.namespace_key = document.namespace_key
         AND version.version = document.current_version
        WHERE document.namespace_key = %s
          AND document.deleted_at IS NULL
        ON CONFLICT DO NOTHING
        """,
        (wiki_version_id, source.namespace_key),
    )
    count_cursor = await connection.execute(
        """
        SELECT
            COUNT(DISTINCT snapshot.document_version_id) AS document_count,
            COUNT(chunk.id) AS chunk_count
        FROM agent.wiki_version_documents AS snapshot
        LEFT JOIN agent.wiki_chunks AS chunk
          ON chunk.document_version_id = snapshot.document_version_id
         AND chunk.namespace_key = snapshot.namespace_key
         AND chunk.is_searchable
        WHERE snapshot.wiki_version_id = %s
        """,
        (wiki_version_id,),
    )
    counts = await count_cursor.fetchone()
    chunk_count = int(counts["chunk_count"])
    await connection.execute(
        """
        UPDATE agent.wiki_versions
        SET status = 'retired'
        WHERE user_id = %s AND status = 'active' AND id <> %s
        """,
        (source.user_id, wiki_version_id),
    )
    await connection.execute(
        """
        UPDATE agent.wiki_versions
        SET
            status = 'active',
            document_count = %s,
            chunk_count = %s,
            activated_at = clock_timestamp()
        WHERE id = %s
        """,
        (int(counts["document_count"]), chunk_count, wiki_version_id),
    )
    return PersistedWikiBuild(
        wiki_version_id=str(wiki_version_id),
        wiki_version=wiki_version,
        affected_documents=persisted,
        chunk_count=chunk_count,
    )


async def get_wiki_chunks_for_embedding(
    connection: AsyncConnection[DictRow],
    *,
    namespace_key: str,
    document_version_ids: Sequence[str],
) -> list[WikiChunkForEmbedding]:
    """영향받은 Wiki 문서 Version의 검색 가능 Chunk를 순서대로 조회한다."""
    if not document_version_ids:
        return []
    cursor = await connection.execute(
        """
        SELECT id, content
        FROM agent.wiki_chunks
        WHERE namespace_key = %s
          AND document_version_id = ANY(%s::uuid[])
          AND is_searchable
        ORDER BY document_version_id, chunk_index
        """,
        (namespace_key, list(document_version_ids)),
    )
    rows = await cursor.fetchall()
    return [
        WikiChunkForEmbedding(chunk_id=str(row["id"]), content=row["content"])
        for row in rows
    ]


async def persist_wiki_embeddings(
    connection: AsyncConnection[DictRow],
    *,
    namespace_key: str,
    model_name: str,
    values: Sequence[WikiEmbeddingValue],
) -> int:
    """Chunk Embedding을 모델 설정 Version과 함께 멱등 Upsert한다."""
    if not values:
        return 0
    config_key = f"personal-wiki/{model_name}"
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (config_key,),
    )
    config_cursor = await connection.execute(
        """
        SELECT id, version
        FROM agent.embedding_configs
        WHERE config_key = %s AND status = 'active'
        ORDER BY version DESC
        LIMIT 1
        """,
        (config_key,),
    )
    config = await config_cursor.fetchone()
    if config is None:
        insert_cursor = await connection.execute(
            """
            INSERT INTO agent.embedding_configs (
                config_key,
                version,
                provider,
                model_name,
                dimensions,
                distance_metric,
                chunk_policy_version,
                status
            )
            SELECT
                %s,
                COALESCE(MAX(version), 0) + 1,
                'openai',
                %s,
                1536,
                'cosine',
                'markdown-heading-v1',
                'active'
            FROM agent.embedding_configs
            WHERE config_key = %s
            RETURNING id, version
            """,
            (config_key, model_name, config_key),
        )
        config = await insert_cursor.fetchone()

    for value in values:
        if len(value.embedding) != 1536:
            raise ValueError(
                f"Wiki Embedding은 1536차원여야 합니다: {len(value.embedding)}"
            )
        vector_literal = "[" + ",".join(str(item) for item in value.embedding) + "]"
        await connection.execute(
            """
            INSERT INTO agent.wiki_embeddings (
                chunk_id,
                namespace_key,
                embedding_config_id,
                model_name,
                model_version,
                embedding,
                content_hash
            ) VALUES (%s, %s, %s, %s, %s, %s::vector, %s)
            ON CONFLICT (chunk_id, embedding_config_id) DO UPDATE
            SET
                model_name = EXCLUDED.model_name,
                model_version = EXCLUDED.model_version,
                embedding = EXCLUDED.embedding,
                content_hash = EXCLUDED.content_hash
            """,
            (
                value.chunk_id,
                namespace_key,
                config["id"],
                model_name,
                str(config["version"]),
                vector_literal,
                compute_content_hash(value.content),
            ),
        )
    return len(values)
