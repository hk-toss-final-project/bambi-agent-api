"""기능 구현 모듈.

DB-002, DB-003, DB-004, DB-005, DB-006, DB-007 기능의 실제 구현 위치를 제공한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from collections.abc import Mapping, Sequence
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
    head_current_version: int | None = None


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
    stored_relation_count: int = 0
    superseded_relation_count: int = 0


@dataclass(frozen=True, slots=True)
class RelationSupportSyncResult:
    """한 번의 Build에서 동기화한 Wiki 관계 근거와 수명주기 집계."""

    observed_relation_count: int
    stored_support_count: int
    superseded_support_count: int
    superseded_relation_count: int


@dataclass(frozen=True, slots=True)
class _RelationPersistenceValues:
    """관계 계획 Metadata에서 검증해 분리한 영속화 전용 값."""

    metadata: dict[str, object]
    provenance_kind: str
    confidence: float
    review_status: str
    evidence: str | None
    model_name: str | None
    model_version: str | None
    prompt_key: str | None
    prompt_version: str | None


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


@dataclass(frozen=True, slots=True)
class WikiNodeEmbedding:
    """현재 Wiki 노드의 검색 Chunk Vector를 평균한 후보 표현."""

    document_kind: str
    document_key: str
    embedding: tuple[float, ...]


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
            document.current_version AS head_current_version,
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
          AND document.status = 'active'
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
        head_current_version=int(row.get("head_current_version", row["version"])),
    )


async def list_user_source_versions_for_rebuild(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
) -> list[UserSourceDocumentForAgent]:
    """전체 Wiki 재구성에 쓸 삭제되지 않은 원본의 현재 Version을 조회한다."""
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
        FROM agent.user_source_documents AS document
        JOIN agent.user_source_document_versions AS version
          ON version.source_document_id = document.id
         AND version.namespace_key = document.namespace_key
         AND version.version = document.current_version
        WHERE document.user_id = %s
          AND document.namespace_key = %s
          AND document.status = 'active'
          AND document.deleted_at IS NULL
          AND version.raw_content IS NOT NULL
        ORDER BY
            CASE
                WHEN document.source_type = 'onboarding_seed' THEN 0
                ELSE 1
            END,
            document.created_at,
            document.id
        """,
        (user_id, f"user/{user_id}"),
    )
    rows = await cursor.fetchall()
    return [
        UserSourceDocumentForAgent(
            source_document_id=str(row["source_document_id"]),
            source_document_version_id=str(row["source_document_version_id"]),
            source_event_id=(
                str(row["source_event_id"]) if row["source_event_id"] else None
            ),
            user_id=row["user_id"],
            namespace_key=row["namespace_key"],
            source_type=row["source_type"],
            canonical_url=row["canonical_url"],
            version=int(row["version"]),
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
            head_current_version=int(row["version"]),
        )
        for row in rows
    ]


async def supersede_personal_wiki_for_rebuild(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
) -> int:
    """전체 재구성 저장 직전에 기존 파생 Wiki를 대체 상태로 전환한다.

    호출자가 모든 LLM 호출·품질 검증을 끝낸 후 최종 저장 Transaction
    안에서만 호출해야 한다. 후속 저장이 실패하면 이 변경도 같이 rollback된다.
    """
    namespace_key = f"user/{user_id}"
    await connection.execute(
        """
        DELETE FROM agent.wiki_version_documents AS snapshot
        USING agent.wiki_versions AS build
        WHERE snapshot.wiki_version_id = build.id
          AND build.user_id = %s
          AND build.built_by_job_id = %s
        """,
        (user_id, job_id),
    )
    await connection.execute(
        """
        UPDATE agent.wiki_relation_supports
        SET status = 'superseded',
            superseded_at = clock_timestamp(),
            updated_at = clock_timestamp()
        WHERE namespace_key = %s AND status = 'active'
        """,
        (namespace_key,),
    )
    await connection.execute(
        """
        UPDATE agent.wiki_document_relations
        SET status = 'superseded',
            superseded_at = clock_timestamp(),
            updated_at = clock_timestamp()
        WHERE namespace_key = %s AND status = 'active'
        """,
        (namespace_key,),
    )
    cursor = await connection.execute(
        """
        UPDATE agent.wiki_documents
        SET status = 'superseded',
            deleted_at = clock_timestamp(),
            updated_at = clock_timestamp()
        WHERE namespace_key = %s
          AND knowledge_scope = 'personal'
          AND deleted_at IS NULL
        RETURNING id
        """,
        (namespace_key,),
    )
    return len(await cursor.fetchall())


async def retire_personal_wiki_without_sources(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
) -> dict[str, int]:
    """활성 원본이 하나도 없을 때 개인 Wiki 파생물을 검색·활성 상태에서 내린다."""
    namespace_key = f"user/{user_id}"
    superseded_document_count = await supersede_personal_wiki_for_rebuild(
        connection, user_id=user_id, job_id=job_id
    )
    chunk_cursor = await connection.execute(
        """
        UPDATE agent.wiki_chunks
        SET is_searchable = false
        WHERE namespace_key = %s AND is_searchable
        RETURNING id
        """,
        (namespace_key,),
    )
    unsearchable_chunk_count = len(await chunk_cursor.fetchall())
    await connection.execute(
        """
        UPDATE agent.wiki_versions
        SET status = 'retired'
        WHERE user_id = %s AND status = 'active'
        """,
        (user_id,),
    )
    await connection.execute(
        """
        UPDATE agent.user_interest_profiles
        SET status = 'retired'
        WHERE user_id = %s AND status = 'active'
        """,
        (user_id,),
    )
    return {
        "superseded_document_count": superseded_document_count,
        "unsearchable_chunk_count": unsearchable_chunk_count,
    }


async def update_full_wiki_rebuild_summary(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    wiki_version_id: str,
    source_count: int,
    affected_document_count: int,
    superseded_document_count: int,
    quality_metrics: Mapping[str, int | float] | None = None,
) -> None:
    """Full Rebuild Wiki Version에 전체 교체 범위 요약을 기록한다.

    `quality_metrics`(WBA-014 결과의 `.metrics`)를 함께 남기면, 재구성마다
    새로 생기는 이 Row들을 `version` 순으로 훑는 것만으로 고아 문서·중복·
    모순 건수가 시간에 따라 나아지는지 추이를 볼 수 있다. 별도 이력 테이블을
    만들지 않고 이미 재구성 단위로 쌓이는 Snapshot에 얹는 방식이다.
    """
    summary: dict[str, object] = {
        "mode": "full_rebuild",
        "source_count": source_count,
        "affected_document_count": affected_document_count,
        "superseded_document_count": superseded_document_count,
    }
    if quality_metrics is not None:
        summary["quality_metrics"] = dict(quality_metrics)
    await connection.execute(
        """
        UPDATE agent.wiki_versions
        SET change_summary = %s
        WHERE id = %s
          AND user_id = %s
          AND namespace_key = %s
        """,
        (
            Jsonb(summary),
            wiki_version_id,
            user_id,
            f"user/{user_id}",
        ),
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
    image_url: str | None = None,
    published_at: datetime | None = None,
    description: str | None = None,
) -> SavedUserSourceVersion | None:
    """수집한 본문 스냅샷을 내용이 바뀐 경우에만 새 Version으로 저장한다.

    content_hash가 최신 Version과 같으면 새 Version을 만들지 않고 None을
    반환한다. 리다이렉트가 반영된 최종 URL은 수집 당시 근거를 남기기 위해
    source_metadata.resolved_url로 함께 보존한다. 원문 대표 이미지를 찾았으면
    source_metadata.image_url도 같이 보존해 Wiki를 근거로 쓰는 리포트가 재사용한다.

    Args:
        user_id: 원본 문서 소유 사용자 ID
        source_document_id: user_source_documents Head ID
        source_event_row_id: 이 스냅샷을 만든 wiki_source_events Row ID
        title: 수집된 문서 제목
        raw_content: 정제된 Markdown 본문
        resolved_url: 리다이렉트된 최종 URL
        image_url: 원문 대표 이미지 URL
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
    if image_url is not None:
        source_metadata["image_url"] = image_url
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
          AND document.status = 'active'
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


_RELATION_PROVENANCE_KINDS = frozenset(
    {
        "source_explicit",
        "semantic_inference",
        "user_declared",
        "system_rule",
    }
)
_RELATION_REVIEW_STATUSES = frozenset({"unreviewed", "accepted", "rejected"})


def _optional_relation_trace(value: object) -> str | None:
    """관계 Model·Prompt 추적 값을 비어 있지 않은 문자열로 정규화한다."""
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _relation_persistence_values(
    relation: WikiRelationPlan,
) -> _RelationPersistenceValues:
    """관계 계획 Metadata를 검증해 관계 Head와 Support 컬럼 값으로 분리한다."""
    metadata = dict(relation.metadata)
    metadata.pop("observed_in_current_build", None)

    provenance_kind = str(
        relation.metadata.get("provenance_kind", "source_explicit")
    ).strip()
    if provenance_kind not in _RELATION_PROVENANCE_KINDS:
        raise ValueError(f"허용되지 않은 관계 근거 유형입니다: {provenance_kind}")

    raw_confidence = relation.metadata.get("confidence", 1.0)
    if isinstance(raw_confidence, bool):
        raise ValueError("관계 confidence는 0과 1 사이 숫자여야 합니다.")
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError) as exc:
        raise ValueError("관계 confidence는 0과 1 사이 숫자여야 합니다.") from exc
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("관계 confidence는 0과 1 사이 숫자여야 합니다.")

    review_status = str(
        relation.metadata.get("review_status", "unreviewed")
    ).strip()
    if review_status not in _RELATION_REVIEW_STATUSES:
        raise ValueError(f"허용되지 않은 관계 검토 상태입니다: {review_status}")

    return _RelationPersistenceValues(
        metadata=metadata,
        provenance_kind=provenance_kind,
        confidence=confidence,
        review_status=review_status,
        evidence=_optional_relation_trace(relation.metadata.get("evidence")),
        model_name=_optional_relation_trace(
            relation.metadata.get("model_name", relation.metadata.get("model"))
        ),
        model_version=_optional_relation_trace(relation.metadata.get("model_version")),
        prompt_key=_optional_relation_trace(relation.metadata.get("prompt_key")),
        prompt_version=_optional_relation_trace(
            relation.metadata.get("prompt_version")
        ),
    )


def _relation_metadata_from_row(row: Mapping[str, Any]) -> dict[str, object]:
    """관계 Head의 구조화 컬럼을 기존 Metadata 기반 계약과 함께 반환한다."""
    metadata: dict[str, object] = dict(row.get("metadata") or {})
    for key in (
        "status",
        "provenance_kind",
        "review_status",
        "model_name",
        "model_version",
        "prompt_key",
        "prompt_version",
        "superseded_at",
    ):
        value = row.get(key)
        if value is not None:
            metadata[key] = value
    if row.get("confidence") is not None:
        metadata["confidence"] = float(row["confidence"])
    return metadata


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
            relation.metadata,
            relation.status,
            relation.provenance_kind,
            relation.confidence,
            relation.review_status,
            relation.model_name,
            relation.model_version,
            relation.prompt_key,
            relation.prompt_version,
            relation.superseded_at
        FROM agent.wiki_document_relations AS relation
        JOIN agent.wiki_documents AS source
          ON source.id = relation.source_document_id
         AND source.namespace_key = relation.namespace_key
        JOIN agent.wiki_documents AS target
          ON target.id = relation.target_document_id
         AND target.namespace_key = relation.namespace_key
        WHERE relation.namespace_key = %s
          AND relation.status = 'active'
          AND relation.review_status <> 'rejected'
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
            metadata=_relation_metadata_from_row(row),
        )
        for row in rows
    ]


@dataclass(frozen=True, slots=True)
class RelatedWikiKeyword:
    """관심 키워드와 Wiki 그래프에서 1홉으로 연결된 이웃 노드 하나.

    ``weight``는 같은 이웃으로 향하는 관계 중 가장 강한 유형의 가중치다.
    predicate Row 수가 노드 중요도를 부풀리지 않게 하며 정렬·상한에만 쓴다.
    """

    title: str
    document_kind: str
    weight: float
    relation_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WikiGraphRelationSnapshot:
    """검색 확장 Gate에 전달할 관계 Head와 양 endpoint의 현재 표시 정보."""

    source_document_kind: str
    source_document_key: str
    source_title: str
    source_domain: str | None
    target_document_kind: str
    target_document_key: str
    target_title: str
    target_domain: str | None
    relation_type: str
    status: str
    review_status: str
    provenance_kind: str
    confidence: float
    weight: float
    supported: bool


# 관계 유형별 가중치. load_interest_documents(degree 계산)와 같은 값을 쓴다 —
# 두 곳이 다른 기준으로 "연결이 강하다"를 판단하면 관심사 순위와 확장 순위가
# 어긋난다.
_RELATION_WEIGHT_SQL = """
                CASE relation.relation_type
                    WHEN 'entity_relation' THEN 1.0
                    WHEN 'applies_concept' THEN 1.0
                    WHEN 'related_concept' THEN 0.5
                    WHEN 'instance_of' THEN 1.0
                    WHEN 'subtopic_of' THEN 1.0
                    WHEN 'part_of' THEN 1.0
                    WHEN 'located_in' THEN 1.0
                    WHEN 'occurs_in' THEN 1.0
                    WHEN 'affects' THEN 1.0
                    WHEN 'causes' THEN 1.0
                    WHEN 'associated_with' THEN 0.5
                    ELSE 0.0
                END
"""


async def list_wiki_graph_relation_snapshot(
    connection: AsyncConnection[DictRow],
    *,
    namespace_key: str,
) -> list[WikiGraphRelationSnapshot]:
    """사용자 Wiki Graph의 관계 Head·endpoint 제목·active support를 조회한다.

    관계 상태를 SQL에서 미리 거르지 않는다. Agent 품질 Gate가 superseded,
    rejected, 미지원, provenance별 confidence 미달 Edge를 같은 정책으로 판정해야
    하므로 Head 상태 전체가 필요하다. endpoint 문서는 현재 활성 Entity·Concept로
    제한하고, 조직 여부는 제목을 검색어로 반환하는 Agent 단계에서 사용한다.

    Args:
        connection: 개인 Wiki RLS Scope가 설정된 현재 Transaction 연결
        namespace_key: 조회 대상 사용자 Wiki Namespace

    Returns:
        안정적인 관계 서명 순서의 typed Graph Snapshot
    """
    cursor = await connection.execute(
        f"""
        SELECT
            source.document_kind AS source_document_kind,
            source.document_key AS source_document_key,
            source_version.title AS source_title,
            source.domain AS source_domain,
            target.document_kind AS target_document_kind,
            target.document_key AS target_document_key,
            target_version.title AS target_title,
            target.domain AS target_domain,
            relation.relation_type,
            relation.status,
            relation.review_status,
            relation.provenance_kind,
            relation.confidence::float8 AS confidence,
            ({_RELATION_WEIGHT_SQL})::float8 AS weight,
            EXISTS (
                SELECT 1
                FROM agent.wiki_relation_supports AS support
                WHERE support.relation_id = relation.id
                  AND support.namespace_key = relation.namespace_key
                  AND support.status = 'active'
            ) AS supported
        FROM agent.wiki_document_relations AS relation
        JOIN agent.wiki_documents AS source
          ON source.id = relation.source_document_id
         AND source.namespace_key = relation.namespace_key
        JOIN agent.wiki_document_versions AS source_version
          ON source_version.document_id = source.id
         AND source_version.namespace_key = source.namespace_key
         AND source_version.version = source.current_version
        JOIN agent.wiki_documents AS target
          ON target.id = relation.target_document_id
         AND target.namespace_key = relation.namespace_key
        JOIN agent.wiki_document_versions AS target_version
          ON target_version.document_id = target.id
         AND target_version.namespace_key = target.namespace_key
         AND target_version.version = target.current_version
        WHERE relation.namespace_key = %s
          AND source.document_kind IN ('entity', 'concept')
          AND target.document_kind IN ('entity', 'concept')
          AND source.status = 'active'
          AND target.status = 'active'
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
        WikiGraphRelationSnapshot(
            source_document_kind=str(row["source_document_kind"]),
            source_document_key=str(row["source_document_key"]),
            source_title=str(row["source_title"] or "").strip(),
            source_domain=(
                str(row["source_domain"])
                if row.get("source_domain") is not None
                else None
            ),
            target_document_kind=str(row["target_document_kind"]),
            target_document_key=str(row["target_document_key"]),
            target_title=str(row["target_title"] or "").strip(),
            target_domain=(
                str(row["target_domain"])
                if row.get("target_domain") is not None
                else None
            ),
            relation_type=str(row["relation_type"]),
            status=str(row["status"]),
            review_status=str(row["review_status"]),
            provenance_kind=str(row["provenance_kind"]),
            confidence=float(row["confidence"]),
            weight=float(row["weight"]),
            supported=bool(row["supported"]),
        )
        for row in rows
    ]


async def list_related_wiki_keywords(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    topic: str,
    limit: int = 5,
    lifecycle_aware: bool = True,
) -> list[RelatedWikiKeyword]:
    """관심 키워드와 개인 Wiki에서 직접 연결된 이웃 노드 제목을 조회한다.

    관심 키워드는 Wiki Entity·Concept 노드의 제목에서 나오므로(INT-001),
    제목이 일치하는 노드를 시작점으로 잡고 ``wiki_document_relations``를 양방향
    으로 한 번(1홉)만 따라간다. 2홉은 주제가 흐려지고 비용이 제곱으로 늘어
    설계 문서(§4)에서 제외했다.

    **``organization`` subtype 노드는 이웃에서 뺀다.** 기관·언론사 이름을 뉴스
    검색어로 쓰면 주제가 아니라 그 회사 소식이 걸린다. 2026-08-06 실측:
    '코스피'의 이웃 6개 중 5개가 organization이었고(코스콤·인포스탁·에프앤가이드
    ·한국예탁결제원·KG제로인), 그 검색 결과의 증시 관련 비율이 0~40%에 그쳤다.
    남은 하나인 '코스닥시장'(subtype=other)은 93%였다. 제외 시 수집 45건→30건,
    주제 적합 60%→97%, 소요 30.6초→23.0초.

    Args:
        connection: RLS Scope가 설정된 현재 Transaction 연결
        user_id: 조회 대상 사용자 ID
        topic: 시작점이 될 관심 키워드(노드 제목 또는 document_key)
        limit: 반환할 최대 이웃 수. 0 이하면 조회하지 않는다.
        lifecycle_aware: 관계 lifecycle Migration이 적용된 정상 조회 여부. False는
            Snapshot 조회가 schema 오류로 실패한 배포 전환기의 1-hop 폴백에서만 쓴다.

    Returns:
        연결 강도 내림차순으로 정렬된 이웃 목록. 일치하는 노드가 없거나 이웃이
        없으면 빈 목록.
    """
    normalized_topic = topic.strip()
    if not normalized_topic or limit <= 0:
        return []

    namespace_key = f"user/{user_id}"
    lifecycle_predicate = (
        "AND relation.status = 'active' "
        "AND relation.review_status <> 'rejected'"
        if lifecycle_aware
        else ""
    )
    cursor = await connection.execute(
        f"""
        WITH origin AS (
            SELECT document.id
            FROM agent.wiki_documents AS document
            JOIN agent.wiki_document_versions AS version
              ON version.document_id = document.id
             AND version.namespace_key = document.namespace_key
             AND version.version = document.current_version
            WHERE document.namespace_key = %s
              AND document.document_kind IN ('entity', 'concept')
              AND document.status = 'active'
              AND document.deleted_at IS NULL
              AND (
                    lower(btrim(version.title)) = lower(btrim(%s))
                 OR document.document_key = %s
              )
        )
        SELECT
            peer_version.title AS title,
            peer.document_kind AS document_kind,
            MAX({_RELATION_WEIGHT_SQL})::float8 AS weight,
            array_agg(DISTINCT relation.relation_type) AS relation_types
        FROM agent.wiki_document_relations AS relation
        JOIN origin
          ON origin.id IN (
                 relation.source_document_id,
                 relation.target_document_id
             )
        JOIN agent.wiki_documents AS peer
          ON peer.id = CASE
                 WHEN relation.source_document_id = origin.id
                 THEN relation.target_document_id
                 ELSE relation.source_document_id
             END
         AND peer.namespace_key = relation.namespace_key
        JOIN agent.wiki_document_versions AS peer_version
          ON peer_version.document_id = peer.id
         AND peer_version.namespace_key = peer.namespace_key
         AND peer_version.version = peer.current_version
        WHERE relation.namespace_key = %s
          {lifecycle_predicate}
          AND peer.document_kind IN ('entity', 'concept')
          AND peer.status = 'active'
          AND peer.deleted_at IS NULL
          AND COALESCE(peer.domain, '') <> 'organization'
          AND peer.id NOT IN (SELECT id FROM origin)
        GROUP BY peer.id, peer_version.title, peer.document_kind
        HAVING MAX({_RELATION_WEIGHT_SQL}) > 0
        ORDER BY weight DESC, title ASC
        LIMIT %s
        """,
        (
            namespace_key,
            normalized_topic,
            normalized_topic,
            namespace_key,
            limit,
        ),
    )
    rows = await cursor.fetchall()
    return [
        RelatedWikiKeyword(
            title=str(row["title"] or "").strip(),
            document_kind=str(row["document_kind"] or ""),
            weight=float(row["weight"] or 0.0),
            relation_types=tuple(row["relation_types"] or ()),
        )
        for row in rows
        if str(row["title"] or "").strip()
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


def _relation_signature(
    relation: WikiRelationPlan,
) -> tuple[str, str, str, str, str]:
    """관계 계획 한 건을 Build 안에서 중복 제거할 안정적인 Key로 변환한다."""
    return (
        relation.source_document_kind,
        relation.source_document_key,
        relation.target_document_kind,
        relation.target_document_key,
        relation.relation_type,
    )


def _observed_relations_for_build(plan: WikiBuildPlan) -> list[WikiRelationPlan]:
    """누적 관계 계획에서 이번 원본이 실제로 관측한 관계만 선택한다.

    새 Planner는 신규 관계에 ``observed_in_current_build``를 표시한다. 이전
    Planner와의 호환을 위해 누적 관계 없이 전부 신규인 계획은
    ``extracted_relation_count``로 식별한다. 모호한 누적 계획을 현재 원본의
    근거로 잘못 귀속하는 것보다 빈 목록을 선택하는 편이 안전하다.
    """
    has_explicit_marker = any(
        "observed_in_current_build" in relation.metadata
        for relation in plan.relations
    )
    if has_explicit_marker:
        return [
            relation
            for relation in plan.relations
            if relation.metadata.get("observed_in_current_build") is True
        ]
    if plan.relations and plan.extracted_relation_count == len(plan.relations):
        return list(plan.relations)
    return []


async def sync_wiki_relation_supports(
    connection: AsyncConnection[DictRow],
    *,
    namespace_key: str,
    source_document_id: str | None = None,
    source_document_version_id: str,
    job_id: str,
    relations: Sequence[WikiRelationPlan],
    observed_relations: Sequence[WikiRelationPlan] | None = None,
) -> RelationSupportSyncResult:
    """관계 Head와 현재 원본 Version의 근거 이력을 원자적으로 동기화한다.

    같은 원본 Version의 이전 active support는 먼저 supersede한다. 이번 Build가
    관측한 관계는 Job 단위 Unique Key로 멱등 저장하고 다시 active로 만든다.
    다른 원본의 support가 남아 있는 관계는 유지하며, 마지막 active support가
    사라진 관계 Head만 supersede한다.

    Args:
        connection: 개인 Wiki RLS Scope가 설정된 현재 Transaction 연결
        namespace_key: 관계와 원본이 속한 사용자 Namespace
        source_document_id: 최신 Version이 대체하는 논리 원본 문서 ID. 전달하면
            이 문서의 과거 Version support도 함께 supersede한다.
        source_document_version_id: 이번 Build가 읽은 사용자 원본 Version ID
        job_id: 같은 Build 재시도를 식별할 Agent Job ID
        relations: 현재 Wiki 계획에 포함할 관계. 기존 호출 호환을 위해 Head는
            모두 Upsert하지만 현재 원본의 근거로 자동 귀속하지 않는다.
        observed_relations: 이번 원본에서 실제 관측한 관계. 생략하면 relations
            전체를 관측 관계로 간주한다.

    Returns:
        저장·supersede한 관계 support와 Head 집계
    """
    observed = list(relations if observed_relations is None else observed_relations)
    all_by_signature = {_relation_signature(relation): relation for relation in relations}
    for relation in observed:
        all_by_signature.setdefault(_relation_signature(relation), relation)

    stale_cursor = await connection.execute(
        """
        UPDATE agent.wiki_relation_supports AS support
        SET
            status = 'superseded',
            superseded_at = clock_timestamp()
        WHERE support.namespace_key = %s
          AND (
                support.source_document_version_id = %s
                OR EXISTS (
                    SELECT 1
                    FROM agent.user_source_document_versions AS source_version
                    WHERE source_version.id = support.source_document_version_id
                      AND source_version.namespace_key = support.namespace_key
                      AND source_version.source_document_id = %s
                )
          )
          AND support.status = 'active'
        RETURNING support.relation_id
        """,
        (
            namespace_key,
            source_document_version_id,
            source_document_id,
        ),
    )
    stale_rows = await stale_cursor.fetchall()
    touched_relation_ids = {row["relation_id"] for row in stale_rows}

    document_cursor = await connection.execute(
        """
        SELECT id, document_kind, document_key
        FROM agent.wiki_documents
        WHERE namespace_key = %s AND deleted_at IS NULL
        """,
        (namespace_key,),
    )
    document_rows = await document_cursor.fetchall()
    document_ids = {
        (row["document_kind"], row["document_key"]): row["id"]
        for row in document_rows
    }

    head_ids: dict[tuple[str, str, str, str, str], object] = {}
    for signature, relation in all_by_signature.items():
        source_id = document_ids.get(
            (relation.source_document_kind, relation.source_document_key)
        )
        target_id = document_ids.get(
            (relation.target_document_kind, relation.target_document_key)
        )
        if source_id is None or target_id is None or source_id == target_id:
            continue
        values = _relation_persistence_values(relation)
        head_cursor = await connection.execute(
            """
            INSERT INTO agent.wiki_document_relations (
                source_document_id,
                target_document_id,
                namespace_key,
                relation_type,
                metadata,
                status,
                provenance_kind,
                confidence,
                review_status,
                model_name,
                model_version,
                prompt_key,
                prompt_version,
                superseded_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                'active', %s, %s, %s, %s, %s, %s, %s, NULL
            )
            ON CONFLICT (source_document_id, target_document_id, relation_type)
            DO UPDATE SET
                metadata = EXCLUDED.metadata,
                status = 'active',
                provenance_kind = EXCLUDED.provenance_kind,
                confidence = EXCLUDED.confidence,
                review_status = EXCLUDED.review_status,
                model_name = EXCLUDED.model_name,
                model_version = EXCLUDED.model_version,
                prompt_key = EXCLUDED.prompt_key,
                prompt_version = EXCLUDED.prompt_version,
                superseded_at = NULL
            RETURNING id
            """,
            (
                source_id,
                target_id,
                namespace_key,
                relation.relation_type,
                Jsonb(values.metadata),
                values.provenance_kind,
                values.confidence,
                values.review_status,
                values.model_name,
                values.model_version,
                values.prompt_key,
                values.prompt_version,
            ),
        )
        head_row = await head_cursor.fetchone()
        head_ids[signature] = head_row["id"]

    stored_support_count = 0
    observed_by_signature = {
        _relation_signature(relation): relation for relation in observed
    }
    for signature, relation in observed_by_signature.items():
        relation_id = head_ids.get(signature)
        if relation_id is None:
            continue
        values = _relation_persistence_values(relation)
        await connection.execute(
            """
            INSERT INTO agent.wiki_relation_supports (
                relation_id,
                namespace_key,
                source_document_version_id,
                build_job_id,
                provenance_kind,
                confidence,
                review_status,
                evidence,
                model_name,
                model_version,
                prompt_key,
                prompt_version,
                metadata,
                status,
                superseded_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                'active', NULL
            )
            ON CONFLICT (relation_id, source_document_version_id, build_job_id)
            DO UPDATE SET
                provenance_kind = EXCLUDED.provenance_kind,
                confidence = EXCLUDED.confidence,
                review_status = EXCLUDED.review_status,
                evidence = EXCLUDED.evidence,
                model_name = EXCLUDED.model_name,
                model_version = EXCLUDED.model_version,
                prompt_key = EXCLUDED.prompt_key,
                prompt_version = EXCLUDED.prompt_version,
                metadata = EXCLUDED.metadata,
                status = 'active',
                superseded_at = NULL
            """,
            (
                relation_id,
                namespace_key,
                source_document_version_id,
                job_id,
                values.provenance_kind,
                values.confidence,
                values.review_status,
                values.evidence,
                values.model_name,
                values.model_version,
                values.prompt_key,
                values.prompt_version,
                Jsonb(values.metadata),
            ),
        )
        touched_relation_ids.add(relation_id)
        stored_support_count += 1

    superseded_relation_count = 0
    if touched_relation_ids:
        touched_ids = list(touched_relation_ids)
        await connection.execute(
            """
            WITH representative AS (
                SELECT DISTINCT ON (support.relation_id)
                    support.relation_id,
                    support.provenance_kind,
                    support.confidence,
                    support.review_status,
                    support.model_name,
                    support.model_version,
                    support.prompt_key,
                    support.prompt_version,
                    support.metadata
                FROM agent.wiki_relation_supports AS support
                WHERE support.namespace_key = %s
                  AND support.relation_id = ANY(%s::uuid[])
                  AND support.status = 'active'
                ORDER BY
                    support.relation_id,
                    CASE support.review_status
                        WHEN 'accepted' THEN 0
                        WHEN 'unreviewed' THEN 1
                        ELSE 2
                    END,
                    support.confidence DESC,
                    support.updated_at DESC,
                    support.id DESC
            )
            UPDATE agent.wiki_document_relations AS relation
            SET
                status = 'active',
                provenance_kind = representative.provenance_kind,
                confidence = representative.confidence,
                review_status = representative.review_status,
                model_name = representative.model_name,
                model_version = representative.model_version,
                prompt_key = representative.prompt_key,
                prompt_version = representative.prompt_version,
                metadata = representative.metadata,
                superseded_at = NULL
            FROM representative
            WHERE relation.id = representative.relation_id
              AND relation.namespace_key = %s
            """,
            (namespace_key, touched_ids, namespace_key),
        )
        superseded_cursor = await connection.execute(
            """
            UPDATE agent.wiki_document_relations AS relation
            SET
                status = 'superseded',
                superseded_at = COALESCE(
                    relation.superseded_at,
                    clock_timestamp()
                )
            WHERE relation.namespace_key = %s
              AND relation.id = ANY(%s::uuid[])
              AND NOT EXISTS (
                    SELECT 1
                    FROM agent.wiki_relation_supports AS support
                    WHERE support.relation_id = relation.id
                      AND support.namespace_key = relation.namespace_key
                      AND support.status = 'active'
              )
              AND relation.status <> 'superseded'
            RETURNING relation.id
            """,
            (namespace_key, touched_ids),
        )
        superseded_rows = await superseded_cursor.fetchall()
        superseded_relation_count = len(superseded_rows)

    return RelationSupportSyncResult(
        observed_relation_count=len(observed_by_signature),
        stored_support_count=stored_support_count,
        superseded_support_count=len(stale_rows),
        superseded_relation_count=superseded_relation_count,
    )


async def _count_wiki_relations(
    connection: AsyncConnection[DictRow], *, namespace_key: str
) -> int:
    """Namespace에 현재 저장된 개인 Wiki 관계 수를 조회한다."""
    cursor = await connection.execute(
        """
        SELECT COUNT(*) AS relation_count
        FROM agent.wiki_document_relations AS relation
        JOIN agent.wiki_documents AS source
          ON source.id = relation.source_document_id
         AND source.namespace_key = relation.namespace_key
        JOIN agent.wiki_documents AS target
          ON target.id = relation.target_document_id
         AND target.namespace_key = relation.namespace_key
        WHERE relation.namespace_key = %s
          AND relation.status = 'active'
          AND relation.review_status <> 'rejected'
          AND source.deleted_at IS NULL
          AND target.deleted_at IS NULL
        """,
        (namespace_key,),
    )
    row = await cursor.fetchone()
    return int(row["relation_count"])


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

    relation_sync = await sync_wiki_relation_supports(
        connection,
        namespace_key=source.namespace_key,
        source_document_id=source.source_document_id,
        source_document_version_id=source.source_document_version_id,
        job_id=job_id,
        relations=plan.relations,
        observed_relations=_observed_relations_for_build(plan),
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
          AND document.status = 'active'
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
    stored_relation_count = await _count_wiki_relations(
        connection, namespace_key=source.namespace_key
    )
    return PersistedWikiBuild(
        wiki_version_id=str(wiki_version_id),
        wiki_version=wiki_version,
        affected_documents=persisted,
        chunk_count=chunk_count,
        stored_relation_count=stored_relation_count,
        superseded_relation_count=relation_sync.superseded_relation_count,
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


def _parse_vector_text(value: object) -> tuple[float, ...]:
    """pgvector의 문자열 표현을 float tuple로 변환한다."""
    text = str(value or "").strip()
    if not text.startswith("[") or not text.endswith("]"):
        return ()
    try:
        return tuple(float(item) for item in text[1:-1].split(","))
    except ValueError:
        return ()


async def list_wiki_node_embeddings(
    connection: AsyncConnection[DictRow],
    *,
    namespace_key: str,
    model_name: str,
) -> list[WikiNodeEmbedding]:
    """활성 Entity·Concept의 현재 Embedding을 노드별 평균 Vector로 조회한다.

    반환 Vector는 Relation Linker의 후보 recall에만 쓰이며 Edge를 자동으로
    생성하지 않는다. 현재 문서 Version과 활성 모델 설정을 고정해
    재임베딩 중 서로 다른 모델 Vector가 섞이지 않게 한다.
    """
    cursor = await connection.execute(
        """
        SELECT
            document.document_kind,
            document.document_key,
            embedding.embedding::text AS embedding
        FROM agent.wiki_documents AS document
        JOIN agent.wiki_document_versions AS version
          ON version.document_id = document.id
         AND version.namespace_key = document.namespace_key
         AND version.version = document.current_version
        JOIN agent.wiki_chunks AS chunk
          ON chunk.document_version_id = version.id
         AND chunk.namespace_key = version.namespace_key
         AND chunk.is_searchable
        JOIN agent.wiki_embeddings AS embedding
          ON embedding.chunk_id = chunk.id
         AND embedding.namespace_key = chunk.namespace_key
        JOIN agent.embedding_configs AS config
          ON config.id = embedding.embedding_config_id
         AND config.status = 'active'
         AND config.model_name = %s
        WHERE document.namespace_key = %s
          AND document.document_kind IN ('entity', 'concept')
          AND document.status = 'active'
          AND document.deleted_at IS NULL
        ORDER BY document.document_kind, document.document_key, chunk.chunk_index
        """,
        (model_name, namespace_key),
    )
    rows = await cursor.fetchall()
    grouped: dict[tuple[str, str], list[tuple[float, ...]]] = {}
    for row in rows:
        vector = _parse_vector_text(row["embedding"])
        if vector:
            grouped.setdefault(
                (row["document_kind"], row["document_key"]), []
            ).append(vector)
    result: list[WikiNodeEmbedding] = []
    for (document_kind, document_key), vectors in grouped.items():
        dimensions = len(vectors[0])
        compatible = [vector for vector in vectors if len(vector) == dimensions]
        if not compatible:
            continue
        result.append(
            WikiNodeEmbedding(
                document_kind=document_kind,
                document_key=document_key,
                embedding=tuple(
                    sum(vector[index] for vector in compatible) / len(compatible)
                    for index in range(dimensions)
                ),
            )
        )
    return result


async def list_onboarding_wiki_anchor_keys(
    connection: AsyncConnection[DictRow],
    *,
    namespace_key: str,
) -> list[tuple[str, str]]:
    """온보딩 시드를 직접 근거로 가진 현재 Wiki 노드 key를 조회한다."""
    cursor = await connection.execute(
        """
        SELECT DISTINCT document.document_kind, document.document_key
        FROM agent.wiki_documents AS document
        JOIN agent.wiki_document_versions AS version
          ON version.document_id = document.id
         AND version.namespace_key = document.namespace_key
         AND version.version = document.current_version
        JOIN agent.wiki_document_sources AS link
          ON link.wiki_document_version_id = version.id
         AND link.namespace_key = version.namespace_key
        JOIN agent.user_source_document_versions AS source_version
          ON source_version.id = link.source_document_version_id
         AND source_version.namespace_key = link.namespace_key
        JOIN agent.user_source_documents AS source_document
          ON source_document.id = source_version.source_document_id
         AND source_document.namespace_key = source_version.namespace_key
        WHERE document.namespace_key = %s
          AND document.document_kind IN ('entity', 'concept')
          AND document.status = 'active'
          AND document.deleted_at IS NULL
          AND source_document.source_type = 'onboarding_seed'
          AND source_document.status = 'active'
          AND source_document.deleted_at IS NULL
          AND source_version.version = source_document.current_version
        ORDER BY document.document_kind, document.document_key
        """,
        (namespace_key,),
    )
    return [
        (str(row["document_kind"]), str(row["document_key"]))
        for row in await cursor.fetchall()
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
