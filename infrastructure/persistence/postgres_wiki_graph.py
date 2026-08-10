"""PostgreSQL 기반 개인 Wiki Graph 조회 저장소.

사용자 RLS Scope 안에서 현재 Entity·Concept Head와 최신 Version,
wiki_document_relations를 읽어 Obsidian 스타일 Graph 응답으로 조립한다.
"""

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from shared.wiki_models import InterestCandidate, WikiClassification
from agent.wiki_builder.api import wba_018
from domain.personal_wiki.source_events.api import wse_010
from infrastructure.persistence.api import (
    delete_wiki_document_and_record_event,
    enqueue_wiki_rebuild_for_source,
    load_interest_documents_for_user,
    load_recent_feedback_signals_for_user,
    reset_personal_wiki,
    save_interest_profile_for_user,
    save_mcp_source_submission,
)
from infrastructure.sources.connectors.api import LatestArticle


type DictRow = dict[str, Any]


def build_wiki_graph_payload(
    *,
    user_id: str,
    node_rows: Sequence[Mapping[str, Any]],
    edge_rows: Sequence[Mapping[str, Any]],
    wiki_version: Mapping[str, Any] | None,
) -> Mapping[str, object]:
    """조회 Row를 API가 사용할 Wiki Graph Payload로 조립한다."""
    namespace_key = f"user/{user_id}"
    node_ids = {str(row["id"]) for row in node_rows}
    edges = []
    neighbors: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for row in edge_rows:
        source_id = str(row["source_document_id"])
        target_id = str(row["target_document_id"])
        if source_id not in node_ids or target_id not in node_ids:
            continue
        neighbors[source_id].add(target_id)
        neighbors[target_id].add(source_id)
        edges.append(
            {
                "id": f"{source_id}:{row['relation_type']}:{target_id}",
                "source": source_id,
                "target": target_id,
                "relation_type": row["relation_type"],
                "metadata": dict(row["metadata"] or {}),
            }
        )

    nodes = []
    for row in node_rows:
        node_id = str(row["id"])
        metadata = dict(row["source_metadata"] or {})
        aliases_value = metadata.get("aliases", [])
        aliases = (
            [str(alias) for alias in aliases_value]
            if isinstance(aliases_value, list)
            else []
        )
        nodes.append(
            {
                "id": node_id,
                "document_kind": row["document_kind"],
                "document_key": row["document_key"],
                "title": row["title"],
                "subtype": row["subtype"],
                "summary": row["summary"],
                "aliases": aliases,
                "file_path": row["file_path"],
                "version": row["version"],
                "updated_at": row["updated_at"],
                "markdown": row["normalized_content"] or "",
                "degree": len(neighbors[node_id]),
            }
        )

    entity_count = sum(
        int(node["document_kind"] == "entity") for node in nodes
    )
    concept_count = len(nodes) - entity_count
    return {
        "user_id": user_id,
        "namespace_key": namespace_key,
        "wiki_version": wiki_version["version"] if wiki_version else None,
        "generated_at": wiki_version["activated_at"] if wiki_version else None,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "entity_count": entity_count,
            "concept_count": concept_count,
            "orphan_count": sum(int(not value) for value in neighbors.values()),
        },
        "nodes": nodes,
        "edges": edges,
    }


class PostgresWikiGraphRepository:
    """PostgreSQL에서 사용자별 현재 Wiki Graph를 조회한다."""

    def __init__(self, database_url: str) -> None:
        """지연 시작 방식의 Graph 조회용 PostgreSQL Pool을 구성한다."""
        self._pool: AsyncConnectionPool[DictRow] = AsyncConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=4,
            open=False,
            kwargs={"row_factory": dict_row},
        )

    async def startup(self) -> None:
        """Graph 조회용 연결 Pool을 열고 최소 연결을 준비한다."""
        await self._pool.open(wait=True)

    async def shutdown(self) -> None:
        """Graph 조회용 PostgreSQL 연결 Pool을 종료한다."""
        await self._pool.close()

    async def get_graph(self, user_id: str) -> Mapping[str, object]:
        """현재 사용자 Namespace의 Wiki Node·Edge와 집계를 반환한다."""
        namespace_key = f"user/{user_id}"
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('app.user_id', %s, true), "
                    "set_config('app.access_scope', 'user', true)",
                    (user_id,),
                )
                node_cursor = await connection.execute(
                    """
                    SELECT
                        document.id,
                        document.document_kind,
                        document.document_key,
                        document.file_path,
                        COALESCE(document.domain, 'other') AS subtype,
                        document.current_version AS version,
                        document.updated_at,
                        version.title,
                        version.summary,
                        version.normalized_content,
                        version.source_metadata
                    FROM agent.wiki_documents AS document
                    JOIN agent.wiki_document_versions AS version
                      ON version.document_id = document.id
                     AND version.namespace_key = document.namespace_key
                     AND version.version = document.current_version
                    WHERE document.namespace_key = %s
                      AND document.document_kind IN ('entity', 'concept')
                      AND document.status = 'active'
                      AND document.deleted_at IS NULL
                    ORDER BY document.document_kind, document.document_key
                    """,
                    (namespace_key,),
                )
                node_rows = await node_cursor.fetchall()
                edge_cursor = await connection.execute(
                    """
                    SELECT
                        relation.source_document_id,
                        relation.target_document_id,
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
                      AND relation.status = 'active'
                      AND relation.review_status <> 'rejected'
                      AND source.document_kind IN ('entity', 'concept')
                      AND target.document_kind IN ('entity', 'concept')
                      AND source.status = 'active'
                      AND target.status = 'active'
                      AND source.deleted_at IS NULL
                      AND target.deleted_at IS NULL
                    ORDER BY
                        relation.source_document_id,
                        relation.target_document_id,
                        relation.relation_type
                    """,
                    (namespace_key,),
                )
                edge_rows = await edge_cursor.fetchall()
                version_cursor = await connection.execute(
                    """
                    SELECT version, activated_at
                    FROM agent.wiki_versions
                    WHERE user_id = %s AND status = 'active'
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (user_id,),
                )
                wiki_version = await version_cursor.fetchone()

        return build_wiki_graph_payload(
            user_id=user_id,
            node_rows=node_rows,
            edge_rows=edge_rows,
            wiki_version=wiki_version,
        )

    @staticmethod
    async def _set_user_scope(
        connection: Any, *, user_id: str
    ) -> None:
        """Wiki 조회 Transaction에 사용자 RLS Scope를 설정한다."""
        await connection.execute(
            "SELECT set_config('app.user_id', %s, true), "
            "set_config('app.access_scope', 'user', true)",
            (user_id,),
        )

    async def list_documents(
        self,
        user_id: str,
        *,
        document_kind: str | None,
        limit: int,
        offset: int,
    ) -> Mapping[str, object]:
        """사용자 Namespace의 현재 Wiki 문서를 종류 필터와 함께 조회한다."""
        namespace_key = f"user/{user_id}"
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await self._set_user_scope(connection, user_id=user_id)
                count_cursor = await connection.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM agent.wiki_documents
                    WHERE namespace_key = %s
                      AND deleted_at IS NULL
                      AND (%s::text IS NULL OR document_kind = %s::text)
                    """,
                    (namespace_key, document_kind, document_kind),
                )
                count = await count_cursor.fetchone()
                cursor = await connection.execute(
                    """
                    SELECT
                        document.id AS document_id,
                        version.id AS document_version_id,
                        document.document_kind,
                        document.document_key,
                        document.file_path,
                        document.domain,
                        version.title,
                        version.summary,
                        version.version,
                        document.updated_at,
                        COUNT(source.source_document_version_id) AS source_count
                    FROM agent.wiki_documents AS document
                    JOIN agent.wiki_document_versions AS version
                      ON version.document_id = document.id
                     AND version.namespace_key = document.namespace_key
                     AND version.version = document.current_version
                    LEFT JOIN agent.wiki_document_sources AS source
                      ON source.wiki_document_version_id = version.id
                     AND source.namespace_key = version.namespace_key
                    WHERE document.namespace_key = %s
                      AND document.deleted_at IS NULL
                      AND (
                          %s::text IS NULL
                          OR document.document_kind = %s::text
                      )
                    GROUP BY document.id, version.id
                    ORDER BY document.document_kind, document.file_path
                    LIMIT %s OFFSET %s
                    """,
                    (namespace_key, document_kind, document_kind, limit, offset),
                )
                rows = await cursor.fetchall()
        return {
            "user_id": user_id,
            "namespace_key": namespace_key,
            "total": int(count["total"]),
            "items": [
                {
                    **dict(row),
                    "document_id": str(row["document_id"]),
                    "document_version_id": str(row["document_version_id"]),
                    "source_count": int(row["source_count"]),
                }
                for row in rows
            ],
        }

    async def search_documents(
        self, user_id: str, *, query: str, limit: int
    ) -> Sequence[Mapping[str, object]]:
        """사용자 Namespace의 공개 Wiki 문서를 제목·요약·본문 부분 일치로 검색한다."""
        namespace_key = f"user/{user_id}"
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await self._set_user_scope(connection, user_id=user_id)
                cursor = await connection.execute(
                    """
                    SELECT
                        document.id AS document_id,
                        document.document_kind,
                        version.title,
                        version.summary,
                        document.updated_at
                    FROM agent.wiki_documents AS document
                    JOIN agent.wiki_document_versions AS version
                      ON version.document_id = document.id
                     AND version.namespace_key = document.namespace_key
                     AND version.version = document.current_version
                    WHERE document.namespace_key = %s
                      AND document.document_kind IN ('document', 'entity', 'concept')
                      AND document.status = 'active'
                      AND document.deleted_at IS NULL
                      AND position(
                            lower(%s) IN lower(concat_ws(
                                ' ', version.title, version.summary,
                                document.document_key, version.normalized_content
                            ))
                          ) > 0
                    ORDER BY
                        CASE
                            WHEN lower(version.title) = lower(%s) THEN 0
                            WHEN position(lower(%s) IN lower(version.title)) > 0 THEN 1
                            WHEN position(lower(%s) IN lower(COALESCE(version.summary, ''))) > 0 THEN 2
                            ELSE 3
                        END,
                        document.updated_at DESC
                    LIMIT %s
                    """,
                    (namespace_key, query, query, query, query, limit),
                )
                rows = await cursor.fetchall()
        return [
            {
                **dict(row),
                "document_id": str(row["document_id"]),
            }
            for row in rows
        ]

    async def get_document(
        self, user_id: str, document_id: str
    ) -> Mapping[str, object] | None:
        """현재 Wiki 문서 Markdown, 출처와 양방향 관계를 조회한다."""
        namespace_key = f"user/{user_id}"
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await self._set_user_scope(connection, user_id=user_id)
                cursor = await connection.execute(
                    """
                    SELECT
                        document.id AS document_id,
                        version.id AS document_version_id,
                        document.document_kind,
                        document.document_key,
                        document.file_path,
                        document.domain,
                        version.title,
                        version.summary,
                        version.version,
                        document.updated_at,
                        version.normalized_content AS markdown,
                        version.source_metadata,
                        (
                            SELECT COUNT(*)
                            FROM agent.wiki_document_sources AS source_count
                            WHERE source_count.wiki_document_version_id = version.id
                        ) AS source_count
                    FROM agent.wiki_documents AS document
                    JOIN agent.wiki_document_versions AS version
                      ON version.document_id = document.id
                     AND version.namespace_key = document.namespace_key
                     AND version.version = document.current_version
                    WHERE document.id = %s
                      AND document.namespace_key = %s
                      AND document.deleted_at IS NULL
                    """,
                    (document_id, namespace_key),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                source_cursor = await connection.execute(
                    """
                    SELECT
                        source_document.id AS source_document_id,
                        source_version.id AS source_document_version_id,
                        source_document.source_type,
                        source_version.version AS source_version,
                        source_version.title,
                        source_document.canonical_url,
                        link.relation_type
                    FROM agent.wiki_document_sources AS link
                    JOIN agent.user_source_document_versions AS source_version
                      ON source_version.id = link.source_document_version_id
                     AND source_version.namespace_key = link.namespace_key
                    JOIN agent.user_source_documents AS source_document
                      ON source_document.id = source_version.source_document_id
                     AND source_document.namespace_key = source_version.namespace_key
                    WHERE link.wiki_document_version_id = %s
                    ORDER BY source_version.created_at, source_version.id
                    """,
                    (row["document_version_id"],),
                )
                source_rows = await source_cursor.fetchall()
                relation_cursor = await connection.execute(
                    """
                    SELECT
                        CASE
                            WHEN relation.source_document_id = %s THEN 'outgoing'
                            ELSE 'incoming'
                        END AS direction,
                        related.id AS related_document_id,
                        related.document_kind AS related_document_kind,
                        related.document_key AS related_document_key,
                        related_version.title AS related_title,
                        relation.relation_type,
                        relation.metadata
                    FROM agent.wiki_document_relations AS relation
                    JOIN agent.wiki_documents AS related
                      ON related.id = CASE
                          WHEN relation.source_document_id = %s
                          THEN relation.target_document_id
                          ELSE relation.source_document_id
                      END
                     AND related.namespace_key = relation.namespace_key
                    JOIN agent.wiki_document_versions AS related_version
                      ON related_version.document_id = related.id
                     AND related_version.namespace_key = related.namespace_key
                     AND related_version.version = related.current_version
                    WHERE relation.namespace_key = %s
                      AND relation.status = 'active'
                      AND relation.review_status <> 'rejected'
                      AND (%s IN (relation.source_document_id, relation.target_document_id))
                      AND related.status = 'active'
                      AND related.deleted_at IS NULL
                    ORDER BY direction, related.document_kind, related.document_key
                    """,
                    (document_id, document_id, namespace_key, document_id),
                )
                relation_rows = await relation_cursor.fetchall()
        return {
            "user_id": user_id,
            "namespace_key": namespace_key,
            **dict(row),
            "document_id": str(row["document_id"]),
            "document_version_id": str(row["document_version_id"]),
            "source_count": int(row["source_count"]),
            "source_metadata": dict(row["source_metadata"] or {}),
            "sources": [
                {
                    **dict(source),
                    "source_document_id": str(source["source_document_id"]),
                    "source_document_version_id": str(
                        source["source_document_version_id"]
                    ),
                }
                for source in source_rows
            ],
            "relations": [
                {
                    **dict(relation),
                    "related_document_id": str(relation["related_document_id"]),
                    "metadata": dict(relation["metadata"] or {}),
                }
                for relation in relation_rows
            ],
        }

    async def get_wiki_version(
        self, user_id: str, wiki_version_id: str
    ) -> Mapping[str, object] | None:
        """특정 Wiki Build와 당시에 고정된 문서 Version 목록을 조회한다."""
        namespace_key = f"user/{user_id}"
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await self._set_user_scope(connection, user_id=user_id)
                cursor = await connection.execute(
                    """
                    SELECT
                        id AS wiki_version_id,
                        user_id,
                        namespace_key,
                        version,
                        status,
                        document_count,
                        chunk_count,
                        change_summary,
                        created_at,
                        activated_at
                    FROM agent.wiki_versions
                    WHERE id = %s AND user_id = %s AND namespace_key = %s
                    """,
                    (wiki_version_id, user_id, namespace_key),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                document_cursor = await connection.execute(
                    """
                    SELECT
                        document.id AS document_id,
                        version.id AS document_version_id,
                        document.document_kind,
                        document.document_key,
                        snapshot.file_path,
                        version.version,
                        version.title
                    FROM agent.wiki_version_documents AS snapshot
                    JOIN agent.wiki_document_versions AS version
                      ON version.id = snapshot.document_version_id
                     AND version.namespace_key = snapshot.namespace_key
                    JOIN agent.wiki_documents AS document
                      ON document.id = version.document_id
                     AND document.namespace_key = version.namespace_key
                    WHERE snapshot.wiki_version_id = %s
                    ORDER BY snapshot.file_path
                    """,
                    (wiki_version_id,),
                )
                documents = await document_cursor.fetchall()
        return {
            **dict(row),
            "wiki_version_id": str(row["wiki_version_id"]),
            "change_summary": dict(row["change_summary"] or {}),
            "documents": [
                {
                    **dict(document),
                    "document_id": str(document["document_id"]),
                    "document_version_id": str(document["document_version_id"]),
                }
                for document in documents
            ],
        }

    async def load_interest_documents(self, user_id: str) -> Mapping[str, object]:
        """활성 Wiki Build와 관심 키워드 계산에 쓸 노드를 조회한다."""
        async with self._pool.connection() as connection:
            return await load_interest_documents_for_user(
                connection, user_id=user_id
            )

    async def save_interest_profile(
        self,
        user_id: str,
        *,
        wiki_version_id: str,
        candidates: Sequence[InterestCandidate],
    ) -> Mapping[str, object]:
        """계산된 관심 후보를 새 Profile Version과 근거 Row로 저장한다."""
        async with self._pool.connection() as connection:
            return await save_interest_profile_for_user(
                connection,
                user_id=user_id,
                wiki_version_id=wiki_version_id,
                candidates=candidates,
            )

    async def load_recent_feedback_signals(
        self, user_id: str
    ) -> list[dict[str, object]]:
        """최근 사용자 행동 신호를 Topic 단위로 반환한다."""
        async with self._pool.connection() as connection:
            return await load_recent_feedback_signals_for_user(
                connection, user_id=user_id
            )

    async def delete_wiki_document(
        self,
        user_id: str,
        *,
        document_id: str,
        source_event_id: str,
        occurred_at: datetime | None,
        memo: str | None,
    ) -> dict[str, object]:
        """delete 이벤트를 기록하고 Wiki 문서를 soft-delete한다."""
        async with self._pool.connection() as connection:
            return await delete_wiki_document_and_record_event(
                connection,
                user_id=user_id,
                document_id=document_id,
                source_event_id=source_event_id,
                occurred_at=occurred_at,
                memo=memo,
            )

    async def reset_wiki(
        self, user_id: str, *, request_id: str
    ) -> Mapping[str, object]:
        """사용자 원본을 영구 삭제하고 개인 LLM Wiki 상태를 초기화한다."""
        async with self._pool.connection() as connection:
            return await reset_personal_wiki(
                connection,
                user_id=user_id,
                request_id=request_id,
            )

    async def add_source(
        self,
        user_id: str,
        *,
        title: str,
        content: str,
        tags: Sequence[str],
        memo: str | None,
        occurred_at: datetime | None,
    ) -> Mapping[str, object]:
        """MCP Write 도구로 받은 원본을 Build Job 없이 저장만 한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await self._set_user_scope(connection, user_id=user_id)
                persisted = await save_mcp_source_submission(
                    connection,
                    user_id=user_id,
                    title=title,
                    content=content,
                    tags=list(tags),
                    memo=memo,
                    occurred_at=occurred_at,
                )
        return {
            "source_document_id": persisted.source_document_id,
            "source_document_version_id": persisted.source_document_version_id,
            "source_version": persisted.source_version,
        }

    async def save_structured_entry(
        self,
        user_id: str,
        *,
        source_document_version_id: str,
        classification: WikiClassification,
        model: str,
    ) -> Mapping[str, object]:
        """Claude가 MCP로 보낸 분류 결과를 기존 Build 파이프라인으로 검증·저장한다."""
        async with self._pool.connection() as connection:
            persisted, quality = await wba_018(
                connection,
                user_id=user_id,
                source_document_version_id=source_document_version_id,
                classification=classification,
                model=model,
            )
        return {
            "wiki_version_id": persisted.wiki_version_id,
            "affected_document_count": len(persisted.affected_documents),
            "quality_passed": quality.passed,
            "quality_warning_count": int(quality.metrics.get("warning_count", 0)),
        }

    async def trigger_rebuild(
        self, user_id: str, *, source_document_version_id: str, request_id: str | None
    ) -> Mapping[str, object]:
        """저장된 원본 Version을 서버 LLM 파이프라인으로 재구성하도록 Job을 등록한다."""
        request = await wse_010(source_document_version_id)
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await self._set_user_scope(connection, user_id=user_id)
                enqueued = await enqueue_wiki_rebuild_for_source(
                    connection,
                    user_id=user_id,
                    source_document_version_id=request.source_document_version_id,
                    request_id=request_id,
                )
        return {"job_id": enqueued.job_id, "job_created": enqueued.created}

    async def list_interests(self, user_id: str) -> Mapping[str, object] | None:
        """사용자의 활성 관심 Profile과 Topic·근거 문서 목록을 조회한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await self._set_user_scope(connection, user_id=user_id)
                profile_cursor = await connection.execute(
                    """
                    SELECT
                        id,
                        wiki_version_id,
                        version,
                        status,
                        calculated_at
                    FROM agent.user_interest_profiles
                    WHERE user_id = %s AND status = 'active'
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (user_id,),
                )
                profile = await profile_cursor.fetchone()
                if profile is None:
                    return None
                interest_cursor = await connection.execute(
                    """
                    SELECT
                        interest.id AS interest_id,
                        interest.topic,
                        interest.category,
                        interest.score,
                        interest.confidence,
                        interest.attributes AS evidence,
                        COALESCE(
                            array_agg(evidence.document_id::text)
                                FILTER (WHERE evidence.document_id IS NOT NULL),
                            '{}'
                        ) AS document_ids
                    FROM agent.user_interests AS interest
                    LEFT JOIN agent.interest_evidence AS evidence
                      ON evidence.interest_id = interest.id
                    WHERE interest.profile_id = %s AND NOT interest.is_blocked
                    GROUP BY interest.id
                    ORDER BY interest.score DESC, interest.topic
                    """,
                    (profile["id"],),
                )
                interests = await interest_cursor.fetchall()
        return {
            "profile_id": str(profile["id"]),
            "user_id": user_id,
            "wiki_version_id": str(profile["wiki_version_id"]),
            "version": int(profile["version"]),
            "status": profile["status"],
            "calculated_at": profile["calculated_at"],
            "interests": [
                {
                    **dict(interest),
                    "interest_id": str(interest["interest_id"]),
                    "score": float(interest["score"]),
                    "confidence": float(interest["confidence"]),
                    "evidence": dict(interest["evidence"] or {}),
                    "document_ids": list(interest["document_ids"] or []),
                }
                for interest in interests
            ],
        }

    async def save_latest_articles(
        self,
        *,
        provider: str,
        query: str,
        articles: Sequence[LatestArticle],
    ) -> list[Mapping[str, object]]:
        """최신 외부 문서를 Global Namespace의 Version·Chunk로 멱등 저장한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await connection.execute("SET LOCAL app.access_scope = 'system'")
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
                        Jsonb({"managed_by": "latest-information-api"}),
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
                saved_items: list[Mapping[str, object]] = []
                for article in articles:
                    url = article.url.strip()
                    if not url:
                        continue
                    url_key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
                    insert_cursor = await connection.execute(
                        """
                        INSERT INTO agent.global_source_documents (
                            canonical_url,
                            url_key,
                            provider,
                            search_query,
                            source_name,
                            language,
                            title,
                            description,
                            content_status,
                            published_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s)
                        ON CONFLICT (canonical_url) DO NOTHING
                        RETURNING id
                        """,
                        (
                            url,
                            url_key,
                            provider,
                            query,
                            article.source_name or None,
                            article.language or "und",
                            article.title,
                            article.description or None,
                            article.published_at,
                        ),
                    )
                    head = await insert_cursor.fetchone()
                    if head is None:
                        # 이미 캐시에 있는 URL — 기존 문서 ID를 찾아 응답에 담는다.
                        existing_cursor = await connection.execute(
                            """
                            SELECT id
                            FROM agent.global_source_documents
                            WHERE canonical_url = %s
                            """,
                            (url,),
                        )
                        existing = await existing_cursor.fetchone()
                        if existing is None:
                            raise RuntimeError("Global 캐시 문서를 저장하지 못했습니다.")
                        document_id = str(existing["id"])
                        created = False
                        duplicate_count += 1
                    else:
                        document_id = str(head["id"])
                        created = True
                        created_count += 1
                    saved_items.append(
                        {
                            "provider": provider,
                            "title": article.title,
                            "url": url,
                            "description": article.description,
                            "published_at": article.published_at,
                            "source_name": article.source_name,
                            "language": article.language,
                            "document_id": document_id,
                            "created": created,
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
        return saved_items
