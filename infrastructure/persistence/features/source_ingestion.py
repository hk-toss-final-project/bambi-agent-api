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
    EnqueuedWikiBuildJob,
    enqueue_personal_wiki_build_job,
    enqueue_personal_wiki_rebuild_job,
    enqueue_url_collection_job,
)
from infrastructure.persistence.features.personal_wiki import (
    get_user_source_document_version_for_agent,
    mark_url_source_event,
    register_user_url_source,
    save_user_url_document_version,
)

type DictRow = dict[str, Any]


@dataclass(frozen=True, slots=True)
class PersistedMcpSourceSubmission:
    """MCP Write 도구로 저장만 한 원본 Version 식별자.

    Build Job은 등록하지 않는다 — 재빌드는 별도 요청(WSE-010)으로 트리거한다.
    """

    source_document_id: str
    source_document_version_id: str
    source_version: int
    source_event_row_id: str


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


class ContentMarkBindingNotFoundError(Exception):
    """해제할 활성 북마크 원본 연결을 찾을 수 없을 때 발생한다."""

    def __init__(self, source_event_id: str) -> None:
        """찾지 못한 북마크 저장 이벤트 식별자를 보관한다."""
        super().__init__(f"활성 북마크 원본 연결을 찾을 수 없습니다: {source_event_id}")
        self.source_event_id = source_event_id


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
    await connection.execute(
        """
        INSERT INTO agent.user_source_bindings (
            user_id,
            namespace_key,
            source_document_id,
            source_document_version_id,
            source_event_row_id,
            status,
            deleted_at
        ) VALUES (%s, %s, %s, %s, %s, 'active', NULL)
        ON CONFLICT (source_event_row_id) DO UPDATE SET
            source_document_id = EXCLUDED.source_document_id,
            source_document_version_id = EXCLUDED.source_document_version_id,
            status = 'active',
            deleted_at = NULL,
            updated_at = clock_timestamp()
        """,
        (
            user_id,
            namespace_key,
            source_document_id,
            source_document_version_id,
            source_event_row_id,
        ),
    )
    return source_document_id, source_document_version_id, source_version


async def _upsert_onboarding_seed_version(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    namespace_key: str,
    source_event_row_id: str,
    title: str,
    content: str,
    content_hash: str,
    metadata: dict[str, object],
) -> tuple[str, str, int]:
    """사용자별 단일 활성 온보딩 Head에 선택 변경 Version을 누적한다."""
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"{namespace_key}:onboarding-seed",),
    )
    head_cursor = await connection.execute(
        """
        SELECT id
        FROM agent.user_source_documents
        WHERE namespace_key = %s
          AND source_type = 'onboarding_seed'
          AND status = 'active'
          AND deleted_at IS NULL
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        FOR UPDATE
        """,
        (namespace_key,),
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
            ) VALUES (%s, %s, 'onboarding_seed', NULL, 1, %s, %s)
            RETURNING id
            """,
            (
                user_id,
                namespace_key,
                content_hash,
                Jsonb({"ingested_by": "onboarding-seed"}),
            ),
        )
        head = await insert_cursor.fetchone()
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
        return source_document_id, str(latest["id"]), int(latest["version"])

    source_version = int(latest["version"]) + 1 if latest else 1
    saved_cursor = await connection.execute(
        """
        INSERT INTO agent.user_source_document_versions (
            source_document_id,
            namespace_key,
            source_event_id,
            version,
            title,
            clipped_on,
            tags,
            raw_content,
            content_format,
            content_hash,
            source_metadata
        ) VALUES (
            %s, %s, %s, %s, %s, CURRENT_DATE, '{}', %s, 'markdown', %s, %s
        )
        RETURNING id
        """,
        (
            source_document_id,
            namespace_key,
            source_event_row_id,
            source_version,
            title,
            content,
            content_hash,
            Jsonb({"origin": "onboarding_seed", **metadata}),
        ),
    )
    saved = await saved_cursor.fetchone()
    await connection.execute(
        """
        UPDATE agent.user_source_documents
        SET
            current_version = %s,
            content_hash = %s,
            metadata = metadata || %s,
            updated_at = clock_timestamp()
        WHERE id = %s
        """,
        (
            source_version,
            content_hash,
            Jsonb(
                {
                    "context_contract_version": metadata.get(
                        "context_contract_version", 1
                    )
                }
            ),
            source_document_id,
        ),
    )
    return source_document_id, str(saved["id"]), source_version


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
    quiet_minutes: int = 0,
    max_wait_minutes: int = 30,
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
        quiet_minutes=quiet_minutes,
        max_wait_minutes=max_wait_minutes,
    )
    return PersistedSourceSubmission(
        source_document_id=source_document_id,
        source_document_version_id=source_document_version_id,
        source_version=source_version,
        source_event_row_id=source_event_row_id,
        job_id=enqueued.job_id,
        job_created=enqueued.created,
    )


async def save_mcp_source_submission(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    title: str,
    content: str,
    tags: list[str],
    memo: str | None,
    occurred_at: datetime | None,
) -> PersistedMcpSourceSubmission:
    """MCP Write 도구가 보낸 원본을 Build Job 없이 멱등 저장한다.

    같은 사용자가 같은 본문을 다시 보내면 새 Source Event나 Version을 만들지
    않는다. Entity·Concept 반영은 이 함수의 책임이 아니며, Claude가 직접
    구조화 문서를 저장하거나(MCPTOOL-013) 재빌드를 요청(WSE-010)해야 한다.
    """
    namespace_key = f"user/{user_id}"
    content_hash = compute_content_hash(content)
    source_event_id = f"mcp-write:{content_hash}"
    event_cursor = await connection.execute(
        """
        INSERT INTO agent.wiki_source_events (
            user_id,
            source_event_id,
            source_type,
            occurred_at,
            payload,
            status
        ) VALUES (
            %s, %s, 'mcp_submission', COALESCE(%s, clock_timestamp()), %s, 'received'
        )
        ON CONFLICT (user_id, source_event_id) DO UPDATE SET
            payload = EXCLUDED.payload,
            updated_at = clock_timestamp()
        RETURNING id
        """,
        (
            user_id,
            source_event_id,
            occurred_at,
            Jsonb(_event_payload(title=title, tags=tags, memo=memo)),
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
        source_type="mcp_submission",
        canonical_url=None,
        source_event_row_id=source_event_row_id,
        title=title,
        author=None,
        published_at=None,
        clipped_on=None,
        description=None,
        tags=tags,
        content=content,
        content_hash=content_hash,
        head_metadata={"ingested_by": "mcp-write-tool"},
        version_metadata={"origin": "mcp_submission"},
    )
    return PersistedMcpSourceSubmission(
        source_document_id=source_document_id,
        source_document_version_id=source_document_version_id,
        source_version=source_version,
        source_event_row_id=source_event_row_id,
    )


async def enqueue_wiki_rebuild_for_source(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_document_version_id: str,
    request_id: str | None,
) -> EnqueuedWikiBuildJob:
    """저장된 원본 Version을 서버 LLM 파이프라인(personal_wiki_build)으로 재구성 요청한다.

    Claude가 구조화 문서를 직접 저장하지 못했을 때(WSE-010)의 폴백 경로다.
    기존 상주 Worker(WORKER-002)가 그대로 처리하므로 별도 Job 타입을 만들지
    않는다. 같은 원본·Version을 다시 요청해도 새 Job을 중복 생성하지 않는다.
    """
    source = await get_user_source_document_version_for_agent(
        connection,
        user_id=user_id,
        source_document_version_id=source_document_version_id,
    )
    if source is None:
        raise ValueError(
            f"개인 Wiki 원본 Version을 찾을 수 없습니다: {source_document_version_id}"
        )
    if not source.source_event_id:
        raise ValueError("이 원본에는 재빌드에 필요한 source_event_id가 없습니다.")
    return await enqueue_personal_wiki_build_job(
        connection,
        user_id=user_id,
        source_document_id=source.source_document_id,
        source_document_version_id=source.source_document_version_id,
        source_version=source.version,
        source_event_id=source.source_event_id,
        feature_id="MCPTOOL-014",
        request_id=request_id,
    )


async def save_onboarding_seed_and_enqueue(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_event_id: str,
    title: str,
    content: str,
    metadata: dict[str, object],
    occurred_at: datetime | None,
    request_id: str,
    quiet_minutes: int = 0,
    max_wait_minutes: int = 30,
) -> PersistedSourceSubmission:
    """온보딩 관심사 시드 문서와 Wiki Build Job을 같은 트랜잭션에 멱등 저장한다.

    WSE-014가 합성한 시드 Markdown을 `onboarding_seed` 원본 Version으로 저장하고
    클리핑과 같은 Personal Wiki Build 파이프라인을 태운다. 실제 저장 근거가 없는
    신규 사용자의 콜드스타트를 위한 경로이며, `(user_id, source_event_id)` 유일
    제약으로 같은 선택의 중복 접수를 막는다(WSE-011).

    Args:
        connection: agent-db 커넥션 (호출자가 트랜잭션·scope를 소유)
        user_id: 시드 원본의 소유자
        source_event_id: 선택 내용으로 만든 멱등 이벤트 ID
        title: 시드 원본 문서 제목
        content: 시드 Markdown 본문
        metadata: 안정 ID·taxonomy 버전 등 근거 메타데이터
        occurred_at: 온보딩 발생 시각
        request_id: 요청 추적 ID
    """
    namespace_key = f"user/{user_id}"
    content_hash = compute_content_hash(content)
    event_cursor = await connection.execute(
        """
        INSERT INTO agent.wiki_source_events (
            user_id,
            source_event_id,
            source_type,
            occurred_at,
            payload,
            status
        ) VALUES (
            %s, %s, 'onboarding_seed', COALESCE(%s, clock_timestamp()), %s, 'received'
        )
        ON CONFLICT (user_id, source_event_id) DO UPDATE SET
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
            Jsonb({**_event_payload(title=title), **metadata}),
        ),
    )
    event_row = await event_cursor.fetchone()
    source_event_row_id = str(event_row["id"])

    (
        source_document_id,
        source_document_version_id,
        source_version,
    ) = await _upsert_onboarding_seed_version(
        connection,
        user_id=user_id,
        namespace_key=namespace_key,
        source_event_row_id=source_event_row_id,
        title=title,
        content=content,
        content_hash=content_hash,
        metadata=metadata,
    )

    enqueued = await enqueue_personal_wiki_build_job(
        connection,
        user_id=user_id,
        source_document_id=source_document_id,
        source_document_version_id=source_document_version_id,
        source_version=source_version,
        source_event_id=source_event_id,
        source_event_row_id=source_event_row_id,
        feature_id="WSE-014",
        request_id=request_id,
        quiet_minutes=quiet_minutes,
        max_wait_minutes=max_wait_minutes,
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
    quiet_minutes: int = 0,
    max_wait_minutes: int = 30,
) -> PersistedSourceSubmission:
    """북마크한 플랫폼 내부 리포트를 원본 Version으로 물질화하고 Build Job을 멱등 등록한다.

    REPORT-021(자동 Wiki 편입 금지)의 짝이다 — 핵심 기준은 "자동이 아니라
    사용자가 명시적으로 저장(북마크)했는가"이지 "내가 만든 콘텐츠인가"가 아니다.
    그래서 대상 리포트를 작성자와 무관하게 전역 유일한 `content_id`로 조회한다.
    내 리포트든 피드에서 본 다른 사용자의 리포트든 같은 경로로 편입되며, 물질화된
    원본과 Build Job은 항상 북마크한 사용자(`user_id`)의 namespace에 귀속된다.
    생성 후보 본문을 `content_mark` 원본으로 복사해 클리핑과 같은 Wiki Build
    파이프라인을 태운다.

    작성자와 무관하게 후보를 읽어야 하므로 호출자는 이 함수를 system scope
    트랜잭션에서 실행한다. 리포트 열람 권한(비공개·차단) 판단은 Service 소유이며
    Agent는 Service가 전달한 content_id를 실행만 한다.

    Args:
        connection: agent-db 커넥션 (호출자가 트랜잭션·system scope를 소유)
        user_id: 북마크한 사용자 ID (물질화 원본의 소유자)
        source_event_id: Service가 부여한 멱등 이벤트 ID
        content_id: 리포트 Row ID 또는 논리 content_id (작성자 무관)
        occurred_at: 사용자가 북마크한 시각
        memo: 북마크 시 남긴 메모
        request_id: 요청 추적 ID

    Raises:
        GeneratedContentNotFoundError: 해당 content_id의 리포트가 없는 경우
    """
    candidate_cursor = await connection.execute(
        """
        SELECT user_id AS author_user_id, content_id, version, content_type,
               title, summary, body
        FROM agent.generated_content_candidates
        WHERE id::text = %s OR content_id = %s
        ORDER BY (id::text = %s) DESC, version DESC
        LIMIT 1
        """,
        (content_id, content_id, content_id),
    )
    candidate = await candidate_cursor.fetchone()
    if candidate is None:
        raise GeneratedContentNotFoundError(content_id)

    author_user_id = str(candidate["author_user_id"])
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
            # 출처 보존: 파이프라인은 내 것/남의 것을 동일하게 처리하되,
            # 원 작성자와 북마크한 사용자는 메타데이터로 남겨 추후 구분·감사에 쓴다.
            "author_user_id": author_user_id,
            "bookmarked_by": user_id,
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
        quiet_minutes=quiet_minutes,
        max_wait_minutes=max_wait_minutes,
    )
    return PersistedSourceSubmission(
        source_document_id=source_document_id,
        source_document_version_id=source_document_version_id,
        source_version=source_version,
        source_event_row_id=source_event_row_id,
        job_id=enqueued.job_id,
        job_created=enqueued.created,
    )


async def deactivate_content_mark_and_enqueue_rebuild(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_event_id: str,
    marked_source_event_id: str,
    content_id: str,
    occurred_at: datetime | None,
    memo: str | None,
    request_id: str,
) -> PersistedSourceSubmission:
    """북마크 이벤트의 활성 원본 연결만 해제하고 전체 재빌드 Job을 등록한다.

    동일한 원본 Head가 다른 저장 이벤트에서도 참조될 수 있으므로 연결이 모두
    사라졌을 때만 Head를 deleted로 전환한다. Wiki 노드·엣지는 직접 부분 삭제하지
    않고 남은 활성 원본 전체를 재구성해 출처와 관계의 정합성을 보존한다.
    """
    existing_cursor = await connection.execute(
        """
        SELECT id, job_id, payload
        FROM agent.wiki_source_events
        WHERE user_id = %s AND source_event_id = %s AND source_type = 'delete'
        FOR UPDATE
        """,
        (user_id, source_event_id),
    )
    existing = await existing_cursor.fetchone()
    if existing is not None and existing["job_id"] is not None:
        payload = dict(existing["payload"] or {})
        return PersistedSourceSubmission(
            source_document_id=str(payload["source_document_id"]),
            source_document_version_id=str(payload["source_document_version_id"]),
            source_version=None,
            source_event_row_id=str(existing["id"]),
            job_id=str(existing["job_id"]),
            job_created=False,
        )

    binding_cursor = await connection.execute(
        """
        SELECT
            binding.id,
            binding.source_document_id,
            binding.source_document_version_id
        FROM agent.user_source_bindings AS binding
        JOIN agent.wiki_source_events AS marked_event
          ON marked_event.id = binding.source_event_row_id
        JOIN agent.user_source_documents AS document
          ON document.id = binding.source_document_id
         AND document.namespace_key = binding.namespace_key
        WHERE marked_event.user_id = %s
          AND marked_event.source_event_id = %s
          AND marked_event.source_type = 'content_mark'
          AND marked_event.source_content_id = %s
          AND binding.namespace_key = %s
          AND binding.status = 'active'
        FOR UPDATE OF binding, document
        """,
        (user_id, marked_source_event_id, content_id, f"user/{user_id}"),
    )
    binding = await binding_cursor.fetchone()
    if binding is None:
        raise ContentMarkBindingNotFoundError(marked_source_event_id)

    source_document_id = str(binding["source_document_id"])
    source_document_version_id = str(binding["source_document_version_id"])
    payload = {
        "marked_source_event_id": marked_source_event_id,
        "source_document_id": source_document_id,
        "source_document_version_id": source_document_version_id,
        **({"memo": memo} if memo else {}),
    }
    event_cursor = await connection.execute(
        """
        INSERT INTO agent.wiki_source_events (
            user_id,
            source_event_id,
            source_type,
            occurred_at,
            source_content_id,
            object_uri,
            payload,
            status
        ) VALUES (
            %s, %s, 'delete', COALESCE(%s, clock_timestamp()), %s, %s, %s, 'received'
        )
        ON CONFLICT (user_id, source_event_id) DO UPDATE SET
            payload = EXCLUDED.payload,
            updated_at = clock_timestamp()
        RETURNING id
        """,
        (
            user_id,
            source_event_id,
            occurred_at,
            content_id,
            source_document_id,
            Jsonb(payload),
        ),
    )
    event = await event_cursor.fetchone()
    source_event_row_id = str(event["id"])
    await connection.execute(
        """
        UPDATE agent.user_source_bindings
        SET status = 'deleted',
            deleted_at = clock_timestamp(),
            updated_at = clock_timestamp()
        WHERE id = %s AND status = 'active'
        """,
        (binding["id"],),
    )
    active_cursor = await connection.execute(
        """
        SELECT COUNT(*) AS active_count
        FROM agent.user_source_bindings
        WHERE source_document_id = %s AND status = 'active'
        """,
        (source_document_id,),
    )
    active = await active_cursor.fetchone()
    if int(active["active_count"]) == 0:
        await connection.execute(
            """
            UPDATE agent.user_source_documents
            SET status = 'deleted',
                deleted_at = clock_timestamp(),
                updated_at = clock_timestamp()
            WHERE id = %s AND namespace_key = %s AND deleted_at IS NULL
            """,
            (source_document_id, f"user/{user_id}"),
        )

    enqueued = await enqueue_personal_wiki_rebuild_job(
        connection,
        user_id=user_id,
        source_event_id=source_event_id,
        source_event_row_id=source_event_row_id,
        removed_source_document_id=source_document_id,
        request_id=request_id,
    )
    return PersistedSourceSubmission(
        source_document_id=source_document_id,
        source_document_version_id=source_document_version_id,
        source_version=None,
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
    quiet_minutes: int = 0,
    max_wait_minutes: int = 30,
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
        quiet_minutes=quiet_minutes,
        max_wait_minutes=max_wait_minutes,
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


async def save_fetched_url_and_enqueue(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_document_id: str,
    source_event_id: str,
    source_event_row_id: str,
    title: str,
    markdown: str,
    resolved_url: str,
    published_at: datetime | None,
    quiet_minutes: int = 0,
    max_wait_minutes: int = 30,
) -> dict[str, object]:
    """Jina 본문을 원본 Version으로 저장하고 후속 Wiki Build Job을 등록한다.

    호출자가 사용자 RLS Scope와 Transaction을 설정한 상태에서 실행한다. 최신
    Version과 본문 해시가 같으면 새 Version·Wiki Job을 만들지 않고 URL 이벤트만
    완료 처리한다.

    Returns:
        저장된 원본 Version과 후속 Wiki Job 식별자 또는 변경 없음 결과
    """
    saved = await save_user_url_document_version(
        connection,
        user_id=user_id,
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
        user_id=user_id,
        source_document_id=source_document_id,
        source_document_version_id=saved.source_version_id,
        source_version=saved.version,
        source_event_id=source_event_id,
        source_event_row_id=source_event_row_id,
        feature_id="SVC-003",
        quiet_minutes=quiet_minutes,
        max_wait_minutes=max_wait_minutes,
    )
    return {
        "source_document_id": source_document_id,
        "source_document_version_id": saved.source_version_id,
        "source_version": saved.version,
        "wiki_build_job_id": enqueued.job_id,
        "unchanged": False,
    }
