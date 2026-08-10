"""Connection 기반 LLM Wiki Navigator 조회 저장소.

호출자가 RLS Scope를 설정한 짧은 Transaction 안에서 Logical Index 후보,
정확한 Page Version, 검증 관계와 사용자 원본 시각을 조회한다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from psycopg import AsyncConnection

type DictRow = dict[str, Any]


def _escape_like(value: str) -> str:
    """ILIKE 검색어의 Wildcard 문자를 리터럴로 Escape한다."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _vector_literal(query_embedding: Sequence[float]) -> str:
    """1536차원 Query Embedding을 검증해 pgvector Literal로 변환한다."""
    if len(query_embedding) != 1536:
        raise ValueError("Navigator Query Embedding은 1536차원이어야 합니다.")
    values: list[float] = []
    for raw_value in query_embedding:
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as error:
            raise ValueError("Navigator Query Embedding에 숫자가 아닌 값이 있습니다.") from error
        if not math.isfinite(value):
            raise ValueError("Navigator Query Embedding에는 유한한 숫자만 허용됩니다.")
        values.append(value)
    return "[" + ",".join(str(value) for value in values) + "]"


async def load_wiki_navigation_keyword_candidates(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    query: str,
    wiki_version_id: str | None,
    limit: int,
) -> list[DictRow]:
    """Logical Index에서 제목·별칭·본문 기반 Page 후보를 조회한다."""
    namespace_key = f"user/{user_id}"
    like_pattern = f"%{_escape_like(query)}%"
    cursor = await connection.execute(
        """
        WITH candidate AS (
            SELECT
                document.id::text AS document_id,
                version.id::text AS document_version_id,
                document.document_kind,
                document.document_key,
                COALESCE(snapshot.file_path, document.file_path) AS file_path,
                version.title,
                COALESCE(version.summary, '') AS summary,
                version.created_at AS updated_at,
                CASE
                    WHEN jsonb_typeof(version.source_metadata -> 'aliases') = 'array'
                    THEN ARRAY(
                        SELECT jsonb_array_elements_text(
                            version.source_metadata -> 'aliases'
                        )
                    )
                    ELSE ARRAY[]::text[]
                END AS aliases,
                lower(version.title) = lower(%s) AS exact_match,
                EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements_text(
                        CASE
                            WHEN jsonb_typeof(
                                version.source_metadata -> 'aliases'
                            ) = 'array'
                            THEN version.source_metadata -> 'aliases'
                            ELSE '[]'::jsonb
                        END
                    ) AS alias(value)
                    WHERE lower(alias.value) = lower(%s)
                ) AS alias_match,
                GREATEST(
                    similarity(version.title, %s),
                    similarity(COALESCE(version.summary, ''), %s),
                    similarity(document.document_key, %s)
                )::float8 AS text_score
            FROM agent.wiki_documents AS document
            JOIN agent.wiki_document_versions AS version
              ON version.document_id = document.id
             AND version.namespace_key = document.namespace_key
            LEFT JOIN agent.wiki_version_documents AS snapshot
              ON snapshot.document_version_id = version.id
             AND snapshot.namespace_key = version.namespace_key
             AND snapshot.wiki_version_id::text = %s
            WHERE document.namespace_key = %s
              AND document.document_kind IN ('entity', 'concept')
              AND document.status = 'active'
              AND document.deleted_at IS NULL
              AND (
                    (%s::text IS NULL AND version.version = document.current_version)
                 OR (%s::text IS NOT NULL AND snapshot.wiki_version_id IS NOT NULL)
              )
              AND (
                    version.title ILIKE %s ESCAPE '\\'
                 OR document.document_key ILIKE %s ESCAPE '\\'
                 OR COALESCE(version.summary, '') ILIKE %s ESCAPE '\\'
                 OR COALESCE(version.normalized_content, '') ILIKE %s ESCAPE '\\'
                 OR EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(
                            CASE
                                WHEN jsonb_typeof(
                                    version.source_metadata -> 'aliases'
                                ) = 'array'
                                THEN version.source_metadata -> 'aliases'
                                ELSE '[]'::jsonb
                            END
                        ) AS alias(value)
                        WHERE alias.value ILIKE %s ESCAPE '\\'
                    )
                 OR to_tsvector(
                        'simple',
                        concat_ws(
                            ' ',
                            version.title,
                            version.summary,
                            version.normalized_content
                        )
                    ) @@ plainto_tsquery('simple', %s)
              )
        )
        SELECT *
        FROM candidate
        ORDER BY
            exact_match DESC,
            alias_match DESC,
            text_score DESC,
            title,
            document_version_id
        LIMIT %s
        """,
        (
            query,
            query,
            query,
            query,
            query,
            wiki_version_id,
            namespace_key,
            wiki_version_id,
            wiki_version_id,
            like_pattern,
            like_pattern,
            like_pattern,
            like_pattern,
            like_pattern,
            query,
            limit,
        ),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def load_wiki_navigation_vector_candidates(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    query_embedding: Sequence[float],
    wiki_version_id: str | None,
    model_name: str,
    limit: int,
) -> list[DictRow]:
    """Logical Index의 Page를 가장 가까운 Chunk Embedding 순으로 조회한다."""
    namespace_key = f"user/{user_id}"
    vector_literal = _vector_literal(query_embedding)
    cursor = await connection.execute(
        """
        WITH query_vector AS (
            SELECT %s::vector AS embedding
        ), ranked AS (
            SELECT
                document.id::text AS document_id,
                version.id::text AS document_version_id,
                document.document_kind,
                document.document_key,
                COALESCE(snapshot.file_path, document.file_path) AS file_path,
                version.title,
                COALESCE(version.summary, '') AS summary,
                version.created_at AS updated_at,
                CASE
                    WHEN jsonb_typeof(version.source_metadata -> 'aliases') = 'array'
                    THEN ARRAY(
                        SELECT jsonb_array_elements_text(
                            version.source_metadata -> 'aliases'
                        )
                    )
                    ELSE ARRAY[]::text[]
                END AS aliases,
                MIN(embedding.embedding <=> query_vector.embedding)::float8
                    AS distance
            FROM agent.wiki_embeddings AS embedding
            JOIN agent.embedding_configs AS config
              ON config.id = embedding.embedding_config_id
             AND config.status = 'active'
             AND config.model_name = %s
            JOIN agent.wiki_chunks AS chunk
              ON chunk.id = embedding.chunk_id
             AND chunk.namespace_key = embedding.namespace_key
             AND chunk.is_searchable
            JOIN agent.wiki_document_versions AS version
              ON version.id = chunk.document_version_id
             AND version.namespace_key = chunk.namespace_key
            JOIN agent.wiki_documents AS document
              ON document.id = version.document_id
             AND document.namespace_key = version.namespace_key
            LEFT JOIN agent.wiki_version_documents AS snapshot
              ON snapshot.document_version_id = version.id
             AND snapshot.namespace_key = version.namespace_key
             AND snapshot.wiki_version_id::text = %s
            CROSS JOIN query_vector
            WHERE embedding.namespace_key = %s
              AND embedding.model_name = %s
              AND document.document_kind IN ('entity', 'concept')
              AND document.status = 'active'
              AND document.deleted_at IS NULL
              AND (
                    (%s::text IS NULL AND version.version = document.current_version)
                 OR (%s::text IS NOT NULL AND snapshot.wiki_version_id IS NOT NULL)
              )
            GROUP BY
                document.id,
                version.id,
                snapshot.file_path
        )
        SELECT *, GREATEST(0.0, 1.0 - distance)::float8 AS vector_score
        FROM ranked
        ORDER BY distance, title, document_version_id
        LIMIT %s
        """,
        (
            vector_literal,
            model_name,
            wiki_version_id,
            namespace_key,
            model_name,
            wiki_version_id,
            wiki_version_id,
            limit,
        ),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def load_wiki_navigation_pages(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    document_version_ids: Sequence[str],
    document_ids: Sequence[str],
    wiki_version_id: str | None,
    max_chunks_per_page: int,
) -> list[DictRow]:
    """선택 Version과 순회 Document ID의 정확한 Page·Chunk를 조회한다."""
    if not document_version_ids and not document_ids:
        return []
    namespace_key = f"user/{user_id}"
    cursor = await connection.execute(
        """
        WITH selected AS (
            SELECT
                document.id AS document_id,
                version.id AS document_version_id,
                CASE
                    WHEN version.id::text = ANY(%s::text[]) THEN 'seed'
                    ELSE 'traversed'
                END AS role,
                CASE
                    WHEN version.id::text = ANY(%s::text[])
                    THEN array_position(%s::text[], version.id::text)
                    ELSE 1000 + COALESCE(
                        array_position(%s::text[], document.id::text),
                        999
                    )
                END AS position
            FROM agent.wiki_documents AS document
            JOIN agent.wiki_document_versions AS version
              ON version.document_id = document.id
             AND version.namespace_key = document.namespace_key
            LEFT JOIN agent.wiki_version_documents AS snapshot
              ON snapshot.document_version_id = version.id
             AND snapshot.namespace_key = version.namespace_key
             AND snapshot.wiki_version_id::text = %s
            WHERE document.namespace_key = %s
              AND document.document_kind IN ('entity', 'concept')
              AND document.status = 'active'
              AND document.deleted_at IS NULL
              AND (
                    version.id::text = ANY(%s::text[])
                 OR (
                        document.id::text = ANY(%s::text[])
                    AND (
                            (%s::text IS NULL AND version.version = document.current_version)
                         OR (%s::text IS NOT NULL AND snapshot.wiki_version_id IS NOT NULL)
                    )
                 )
              )
        )
        SELECT
            selected.document_id::text AS document_id,
            selected.document_version_id::text AS document_version_id,
            document.document_kind,
            document.document_key,
            COALESCE(snapshot.file_path, document.file_path) AS file_path,
            version.title,
            COALESCE(version.summary, '') AS summary,
            COALESCE(version.normalized_content, '') AS markdown,
            version.version,
            version.created_at AS updated_at,
            CASE
                WHEN jsonb_typeof(version.source_metadata -> 'aliases') = 'array'
                THEN ARRAY(
                    SELECT jsonb_array_elements_text(
                        version.source_metadata -> 'aliases'
                    )
                )
                ELSE ARRAY[]::text[]
            END AS aliases,
            selected.role,
            chunk.id::text AS chunk_id,
            chunk.chunk_index,
            chunk.content AS chunk_content,
            chunk.metadata AS chunk_metadata,
            selected.position
        FROM selected
        JOIN agent.wiki_documents AS document
          ON document.id = selected.document_id
        JOIN agent.wiki_document_versions AS version
          ON version.id = selected.document_version_id
        LEFT JOIN agent.wiki_version_documents AS snapshot
          ON snapshot.document_version_id = version.id
         AND snapshot.wiki_version_id::text = %s
        LEFT JOIN LATERAL (
            SELECT candidate.id, candidate.chunk_index, candidate.content,
                   candidate.metadata
            FROM agent.wiki_chunks AS candidate
            WHERE candidate.document_version_id = version.id
              AND candidate.namespace_key = version.namespace_key
              AND candidate.is_searchable
            ORDER BY candidate.chunk_index
            LIMIT %s
        ) AS chunk ON true
        ORDER BY selected.position, chunk.chunk_index NULLS LAST
        """,
        (
            list(document_version_ids),
            list(document_version_ids),
            list(document_version_ids),
            list(document_ids),
            wiki_version_id,
            namespace_key,
            list(document_version_ids),
            list(document_ids),
            wiki_version_id,
            wiki_version_id,
            wiki_version_id,
            max_chunks_per_page,
        ),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def load_wiki_navigation_relations(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    document_ids: Sequence[str],
) -> list[DictRow]:
    """지정 Page에 닿는 active·지원 근거 보유 관계를 조회한다."""
    if not document_ids:
        return []
    namespace_key = f"user/{user_id}"
    cursor = await connection.execute(
        """
        SELECT
            relation.id::text AS relation_id,
            relation.source_document_id::text AS source_document_id,
            relation.target_document_id::text AS target_document_id,
            relation.relation_type,
            relation.confidence::float8 AS confidence,
            relation.provenance_kind,
            relation.review_status,
            COALESCE(relation.metadata ->> 'rationale', '') AS rationale,
            jsonb_agg(
                jsonb_build_object(
                    'source_document_version_id',
                        support.source_document_version_id::text,
                    'provenance_kind', support.provenance_kind,
                    'confidence', support.confidence::float8,
                    'review_status', support.review_status,
                    'evidence', COALESCE(support.evidence, ''),
                    'rationale', COALESCE(
                        support.metadata ->> 'rationale',
                        relation.metadata ->> 'rationale',
                        ''
                    )
                )
                ORDER BY support.confidence DESC, support.id
            ) AS supports
        FROM agent.wiki_document_relations AS relation
        JOIN agent.wiki_documents AS source
          ON source.id = relation.source_document_id
         AND source.namespace_key = relation.namespace_key
        JOIN agent.wiki_documents AS target
          ON target.id = relation.target_document_id
         AND target.namespace_key = relation.namespace_key
        JOIN agent.wiki_relation_supports AS support
          ON support.relation_id = relation.id
         AND support.namespace_key = relation.namespace_key
         AND support.status = 'active'
         AND support.review_status <> 'rejected'
        WHERE relation.namespace_key = %s
          AND relation.status = 'active'
          AND relation.review_status <> 'rejected'
          AND (
                relation.source_document_id::text = ANY(%s::text[])
             OR relation.target_document_id::text = ANY(%s::text[])
          )
          AND source.status = 'active'
          AND target.status = 'active'
          AND source.deleted_at IS NULL
          AND target.deleted_at IS NULL
        GROUP BY relation.id
        ORDER BY
            relation.confidence DESC,
            relation.relation_type,
            relation.id
        """,
        (namespace_key, list(document_ids), list(document_ids)),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def load_wiki_navigation_sources(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    wiki_document_version_ids: Sequence[str],
) -> list[DictRow]:
    """Wiki Page Version의 사용자 원본과 저장·게시 시각을 조회한다."""
    if not wiki_document_version_ids:
        return []
    namespace_key = f"user/{user_id}"
    cursor = await connection.execute(
        """
        SELECT
            link.wiki_document_version_id::text AS wiki_document_version_id,
            source_document.id::text AS source_document_id,
            source_version.id::text AS source_document_version_id,
            source_document.source_type,
            source_version.title,
            source_document.canonical_url AS url,
            link.relation_type,
            COALESCE(source_event.occurred_at, source_version.created_at)
                AS saved_at,
            CASE
                WHEN source_event.occurred_at IS NOT NULL
                THEN 'event_occurred_at'
                ELSE 'version_created_at'
            END AS saved_at_source,
            source_version.created_at AS stored_at,
            source_version.published_at,
            source_version.clipped_on
        FROM agent.wiki_document_sources AS link
        JOIN agent.user_source_document_versions AS source_version
          ON source_version.id = link.source_document_version_id
         AND source_version.namespace_key = link.namespace_key
        JOIN agent.user_source_documents AS source_document
          ON source_document.id = source_version.source_document_id
         AND source_document.namespace_key = source_version.namespace_key
        LEFT JOIN agent.wiki_source_events AS source_event
          ON source_event.id = source_version.source_event_id
         AND source_event.user_id = %s
        WHERE link.namespace_key = %s
          AND link.wiki_document_version_id::text = ANY(%s::text[])
          AND source_document.status = 'active'
          AND source_document.deleted_at IS NULL
        ORDER BY saved_at DESC, source_version.id
        """,
        (user_id, namespace_key, list(wiki_document_version_ids)),
    )
    return [dict(row) for row in await cursor.fetchall()]
