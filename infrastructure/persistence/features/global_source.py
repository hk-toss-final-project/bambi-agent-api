"""기능 구현 모듈.

DB-008, DB-009, DB-010, DB-011, DB-012, DB-013, DB-014 기능의 실제 구현 위치를 제공한다.

이 파일은 위 스캐폴드 기능 함수와 함께, Global Source Collector Worker가
GDELT·Naver로 수집한 뉴스 URL을 Global Namespace(`namespace_key='global'`)에
저장하고, Jina Reader Worker가 그 URL의 본문을 채우기 위해 사용하는 실제
PostgreSQL 함수를 제공한다.

수집과 본문 채우기는 두 단계로 분리된다.
1. 수집 워커: URL 기준으로 중복을 제거하고, 아직 본문이 없는 문서를
   `metadata.content_status = 'pending'` 상태로 저장한다.
2. Jina 워커: pending 문서를 점유(`fetching`)해 본문을 새 Version으로 채우고
   `metadata.content_status = 'fetched'`로 전환한다.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from agent.wiki_builder.features.vault import compute_content_hash
from infrastructure.sources.connectors.features.latest import LatestArticle
from shared.contracts import FeatureRequest, FeatureResult

type DictRow = dict[str, Any]


@dataclass(frozen=True, slots=True)
class GlobalArticleToFetch:
    """Jina Reader Worker가 본문을 채울 대상으로 점유한 Global 기사 하나."""

    document_id: str
    url: str
    current_version: int


def _article_stub_markdown(article: LatestArticle) -> str:
    """본문 수집 전 단계의 기사 메타데이터를 최소 Markdown으로 만든다.

    수집 워커는 아직 본문을 모르므로 제목·설명·원문 링크만 저장한다. Jina
    워커가 이후 전체 본문으로 대체한다.
    """
    lines = [f"# {article.title}".strip(), ""]
    if article.description:
        lines.extend([article.description.strip(), ""])
    lines.append(f"[원문 링크]({article.url})")
    return "\n".join(lines).strip() + "\n"


def _document_key(url: str) -> str:
    """URL을 안정적인 24자 Global 문서 Key로 변환한다."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


async def persist_collected_articles(
    connection: AsyncConnection[DictRow],
    *,
    provider: str,
    query: str,
    articles: list[LatestArticle],
    content_status: str = "pending",
) -> dict[str, object]:
    """수집한 뉴스 기사 URL을 Global Namespace에 중복 없이 저장한다.

    같은 Transaction에서 Global Source(DB-008)와 Collection Run(DB-009)을
    기록하고, URL 기준으로 아직 저장되지 않은 기사만 Global 문서·Version·
    Chunk(DB-010, DB-011)로 새로 저장한다. 이미 있는 URL은 본문 수집 여부와
    무관하게 건너뛴다.

    Args:
        connection: 시스템 Scope가 설정된 DB 연결
        provider: 수집 Provider 이름 (예: gdelt, naver)
        query: 이번 수집에 사용한 검색 키워드 문자열
        articles: Provider가 정규화한 최신 기사 목록
        content_status: 새로 저장한 문서의 초기 본문 상태 (기본 pending)

    Returns:
        source_id, run_id와 수집·생성·중복 건수, 저장된 문서 항목 목록
    """
    source_cursor = await connection.execute(
        """
        INSERT INTO agent.global_sources (
            source_key,
            connector_type,
            display_name,
            status,
            connector_config
        ) VALUES (%s, %s, %s, 'active', %s)
        ON CONFLICT (source_key) DO UPDATE SET
            connector_type = EXCLUDED.connector_type,
            display_name = EXCLUDED.display_name,
            status = 'active',
            updated_at = clock_timestamp()
        RETURNING id
        """,
        (
            f"latest-{provider}",
            provider,
            f"Latest {provider}",
            Jsonb({"managed_by": "global-source-collector"}),
        ),
    )
    source = await source_cursor.fetchone()
    run_cursor = await connection.execute(
        """
        INSERT INTO agent.global_collection_runs (
            source_id,
            status,
            cursor_before
        ) VALUES (%s, 'running', %s)
        RETURNING id
        """,
        (source["id"], Jsonb({"query": query})),
    )
    run = await run_cursor.fetchone()

    created_count = 0
    duplicate_count = 0
    saved_items: list[dict[str, object]] = []
    for article in articles:
        url = article.url.strip()
        if not url:
            continue
        existing_cursor = await connection.execute(
            """
            SELECT id
            FROM agent.wiki_documents
            WHERE namespace_key = 'global'
              AND deleted_at IS NULL
              AND canonical_url = %s
            LIMIT 1
            FOR UPDATE
            """,
            (url,),
        )
        if await existing_cursor.fetchone() is not None:
            duplicate_count += 1
            continue

        markdown = _article_stub_markdown(article)
        content_hash = compute_content_hash(markdown)
        document_key = _document_key(url)
        metadata = {
            "provider": provider,
            "query": query,
            "content_status": content_status,
            "source_name": article.source_name,
            "language": article.language,
            "published_at": (
                article.published_at.isoformat() if article.published_at else None
            ),
        }
        insert_cursor = await connection.execute(
            """
            INSERT INTO agent.wiki_documents (
                knowledge_scope,
                namespace_key,
                source_type,
                canonical_url,
                language,
                current_version,
                content_hash,
                metadata,
                document_kind,
                document_key,
                file_path,
                domain
            ) VALUES (
                'global', 'global', %s, %s, %s, 1, %s, %s,
                'document', %s, %s, %s
            )
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (
                provider,
                url,
                article.language or "und",
                content_hash,
                Jsonb(metadata),
                document_key,
                f"documents/{document_key}.md",
                article.source_name or None,
            ),
        )
        head = await insert_cursor.fetchone()
        if head is None:
            # 같은 Batch나 동시 수집이 먼저 저장한 URL이므로 중복으로 센다.
            duplicate_count += 1
            continue
        document_id = str(head["id"])
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
                source_metadata
            ) VALUES (%s, 'global', 1, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                document_id,
                article.title,
                article.description or None,
                markdown,
                content_hash,
                Jsonb(metadata),
            ),
        )
        version_row = await version_cursor.fetchone()
        await connection.execute(
            """
            INSERT INTO agent.wiki_chunks (
                document_version_id,
                namespace_key,
                chunk_index,
                content,
                metadata
            ) VALUES (%s, 'global', 0, %s, %s)
            """,
            (
                version_row["id"],
                markdown,
                Jsonb({"provider": provider, "query": query}),
            ),
        )
        created_count += 1
        saved_items.append(
            {
                "provider": provider,
                "title": article.title,
                "url": url,
                "document_id": document_id,
                "document_version_id": str(version_row["id"]),
                "content_status": content_status,
                "published_at": article.published_at,
                "source_name": article.source_name,
                "language": article.language,
            }
        )

    await connection.execute(
        """
        UPDATE agent.global_collection_runs
        SET
            status = 'completed',
            fetched_count = %s,
            created_count = %s,
            duplicate_count = %s,
            cursor_after = %s,
            completed_at = clock_timestamp()
        WHERE id = %s
        """,
        (
            len(articles),
            created_count,
            duplicate_count,
            Jsonb({"query": query}),
            run["id"],
        ),
    )
    return {
        "source_id": str(source["id"]),
        "run_id": str(run["id"]),
        "fetched_count": len(articles),
        "created_count": created_count,
        "duplicate_count": duplicate_count,
        "items": saved_items,
    }


async def claim_global_articles_for_fetch(
    connection: AsyncConnection[DictRow],
    *,
    limit: int,
) -> list[GlobalArticleToFetch]:
    """본문이 없는 Global 기사(content_status='pending')를 점유해 반환한다.

    SKIP LOCKED로 pending 문서를 Batch 점유하고 즉시 `fetching` 상태로 바꿔
    다른 Worker가 같은 문서를 중복 수집하지 않게 한다.

    Args:
        connection: 시스템 Scope가 설정된 DB 연결
        limit: 한 번에 점유할 최대 문서 수

    Returns:
        본문을 채울 문서 ID, URL, 현재 Version 목록
    """
    if not 1 <= limit <= 100:
        raise ValueError("Global 기사 Claim limit은 1에서 100 사이여야 합니다.")
    cursor = await connection.execute(
        """
        WITH claimable AS (
            SELECT id
            FROM agent.wiki_documents
            WHERE namespace_key = 'global'
              AND deleted_at IS NULL
              AND canonical_url IS NOT NULL
              AND metadata->>'content_status' = 'pending'
            ORDER BY updated_at
            FOR UPDATE SKIP LOCKED
            LIMIT %s
        )
        UPDATE agent.wiki_documents AS document
        SET
            metadata = jsonb_set(document.metadata, '{content_status}', '"fetching"'),
            updated_at = clock_timestamp()
        FROM claimable
        WHERE document.id = claimable.id
        RETURNING document.id, document.canonical_url, document.current_version
        """,
        (limit,),
    )
    rows = await cursor.fetchall()
    return [
        GlobalArticleToFetch(
            document_id=str(row["id"]),
            url=row["canonical_url"],
            current_version=int(row["current_version"]),
        )
        for row in rows
    ]


async def save_fetched_article_content(
    connection: AsyncConnection[DictRow],
    *,
    document_id: str,
    resolved_url: str,
    title: str,
    markdown: str,
    published_at: datetime | None,
) -> dict[str, object]:
    """Jina Reader가 수집한 본문을 Global 문서의 새 Version으로 저장한다.

    기존 stub Version은 보존하고, 전체 본문을 담은 새 Version과 Chunk를
    추가한 뒤 Head의 최신 Version·Hash와 `content_status='fetched'`를 갱신한다.

    Args:
        connection: 시스템 Scope가 설정된 DB 연결
        document_id: 본문을 채울 Global 문서 ID
        resolved_url: Jina Reader가 리다이렉트까지 반영한 최종 URL
        title: 수집한 본문 제목
        markdown: 수집한 전체 본문 Markdown
        published_at: 본문에서 파싱한 게시 시각 (없으면 None)

    Returns:
        저장한 문서 ID, 새 Version 번호와 Version ID
    """
    head_cursor = await connection.execute(
        """
        SELECT current_version, metadata
        FROM agent.wiki_documents
        WHERE id = %s AND namespace_key = 'global'
        FOR UPDATE
        """,
        (document_id,),
    )
    head = await head_cursor.fetchone()
    if head is None:
        raise RuntimeError(f"Global 문서를 찾을 수 없습니다: {document_id}")
    version = int(head["current_version"]) + 1
    content_hash = compute_content_hash(markdown)
    metadata = dict(head["metadata"] or {})
    metadata.update(
        {
            "content_status": "fetched",
            "resolved_url": resolved_url,
            "fetched_at": datetime.now().astimezone().isoformat(),
            "published_at": (
                published_at.isoformat() if published_at else metadata.get("published_at")
            ),
        }
    )
    version_cursor = await connection.execute(
        """
        INSERT INTO agent.wiki_document_versions (
            document_id,
            namespace_key,
            version,
            title,
            normalized_content,
            content_hash,
            source_metadata
        ) VALUES (%s, 'global', %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (document_id, version, title, markdown, content_hash, Jsonb(metadata)),
    )
    version_row = await version_cursor.fetchone()
    await connection.execute(
        """
        INSERT INTO agent.wiki_chunks (
            document_version_id,
            namespace_key,
            chunk_index,
            content,
            metadata
        ) VALUES (%s, 'global', 0, %s, %s)
        """,
        (version_row["id"], markdown, Jsonb({"source": "jina-reader"})),
    )
    await connection.execute(
        """
        UPDATE agent.wiki_documents
        SET
            current_version = %s,
            content_hash = %s,
            metadata = %s,
            updated_at = clock_timestamp()
        WHERE id = %s
        """,
        (version, content_hash, Jsonb(metadata), document_id),
    )
    return {
        "document_id": document_id,
        "document_version_id": str(version_row["id"]),
        "version": version,
        "content_status": "fetched",
    }


async def mark_global_article_fetch_failed(
    connection: AsyncConnection[DictRow],
    *,
    document_id: str,
    error_code: str,
    error_message: str,
) -> None:
    """본문 수집에 실패한 Global 문서를 failed 상태로 표시한다.

    무한 재시도를 막기 위해 `content_status='failed'`로 전환하고 오류 원인을
    metadata에 보존한다. 관리자가 원인을 확인한 뒤 pending으로 되돌려 재수집할
    수 있다.
    """
    await connection.execute(
        """
        UPDATE agent.wiki_documents
        SET
            metadata = metadata || %s::jsonb,
            updated_at = clock_timestamp()
        WHERE id = %s AND namespace_key = 'global'
        """,
        (
            Jsonb(
                {
                    "content_status": "failed",
                    "fetch_error_code": error_code,
                    "fetch_error_message": error_message[:500],
                }
            ),
            document_id,
        ),
    )


async def db_008(request: FeatureRequest) -> FeatureResult:
    """[DB-008] Global Source 저장.

    외부 수집 Source와 설정을 저장한다.
    """
    raise NotImplementedError("[DB-008] 기능 구현이 필요합니다.")


async def db_009(request: FeatureRequest) -> FeatureResult:
    """[DB-009] Global Collection Run 저장.

    수집 실행 결과와 상태를 저장한다.
    """
    raise NotImplementedError("[DB-009] 기능 구현이 필요합니다.")


async def db_010(request: FeatureRequest) -> FeatureResult:
    """[DB-010] Global 문서 저장.

    수집된 외부 문서와 버전을 저장한다.
    """
    raise NotImplementedError("[DB-010] 기능 구현이 필요합니다.")


async def db_011(request: FeatureRequest) -> FeatureResult:
    """[DB-011] Global Chunk 저장.

    Global Source 검색용 Chunk를 저장한다.
    """
    raise NotImplementedError("[DB-011] 기능 구현이 필요합니다.")


async def db_012(request: FeatureRequest) -> FeatureResult:
    """[DB-012] Global Embedding 저장.

    Global Source의 Vector 데이터를 저장한다.
    """
    raise NotImplementedError("[DB-012] 기능 구현이 필요합니다.")


async def db_013(request: FeatureRequest) -> FeatureResult:
    """[DB-013] Global Trend 저장.

    탐지된 트렌드와 문서 그룹을 저장한다.
    """
    raise NotImplementedError("[DB-013] 기능 구현이 필요합니다.")


async def db_014(request: FeatureRequest) -> FeatureResult:
    """[DB-014] Discovery Candidate 저장.

    생성 및 추천 후보를 저장한다.
    """
    raise NotImplementedError("[DB-014] 기능 구현이 필요합니다.")
