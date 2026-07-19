"""PostgreSQL 기반 개인 Wiki Graph 조회 저장소.

사용자 RLS Scope 안에서 현재 Entity·Concept Head와 최신 Version,
wiki_document_relations를 읽어 Obsidian 스타일 Graph 응답으로 조립한다.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from agent.wiki_builder.api import InterestCandidate
from agent.wiki_builder.features.vault import compute_content_hash
from infrastructure.sources.connectors.api import LatestArticle


def _global_article_markdown(article: LatestArticle) -> str:
    """정규화된 최신 기사를 YAML Frontmatter와 Markdown 본문으로 변환한다."""
    frontmatter = [
        "---",
        f"title: {json.dumps(article.title, ensure_ascii=False)}",
        f"source: {json.dumps(article.url, ensure_ascii=False)}",
        f"provider: {article.provider}",
    ]
    if article.published_at is not None:
        frontmatter.append(f"published: {article.published_at.isoformat()}")
    if article.source_name:
        frontmatter.append(
            f"source_name: {json.dumps(article.source_name, ensure_ascii=False)}"
        )
    frontmatter.extend(["---", "", f"# {article.title}", ""])
    frontmatter.append(article.description or "원문 링크에서 내용을 확인하세요.")
    return "\n".join(frontmatter).strip()

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
    degree = {node_id: 0 for node_id in node_ids}
    for row in edge_rows:
        source_id = str(row["source_document_id"])
        target_id = str(row["target_document_id"])
        if source_id not in node_ids or target_id not in node_ids:
            continue
        degree[source_id] += 1
        degree[target_id] += 1
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
                "degree": degree[node_id],
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
            "orphan_count": sum(int(value == 0) for value in degree.values()),
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
                      AND (%s IN (relation.source_document_id, relation.target_document_id))
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
        """활성 Wiki Build와 관심 키워드 계산에 사용할 현재 문서를 조회한다."""
        namespace_key = f"user/{user_id}"
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await self._set_user_scope(connection, user_id=user_id)
                version_cursor = await connection.execute(
                    """
                    SELECT id, version
                    FROM agent.wiki_versions
                    WHERE user_id = %s AND status = 'active'
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (user_id,),
                )
                wiki_version = await version_cursor.fetchone()
                document_cursor = await connection.execute(
                    """
                    SELECT
                        document.id AS document_id,
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
                      AND document.deleted_at IS NULL
                    ORDER BY document.document_kind, document.document_key
                    """,
                    (namespace_key,),
                )
                documents = await document_cursor.fetchall()
        return {
            "user_id": user_id,
            "wiki_version_id": (
                str(wiki_version["id"]) if wiki_version is not None else None
            ),
            "wiki_version": (
                int(wiki_version["version"]) if wiki_version is not None else None
            ),
            "documents": [
                {
                    **dict(document),
                    "document_id": str(document["document_id"]),
                    "source_metadata": dict(document["source_metadata"] or {}),
                }
                for document in documents
            ],
        }

    async def save_interest_profile(
        self,
        user_id: str,
        *,
        wiki_version_id: str,
        candidates: Sequence[InterestCandidate],
    ) -> Mapping[str, object]:
        """계산된 관심 후보를 새 Profile Version과 근거 Row로 저장한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await self._set_user_scope(connection, user_id=user_id)
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"interest/{user_id}",),
                )
                version_cursor = await connection.execute(
                    """
                    SELECT COALESCE(MAX(version), 0) + 1 AS next_version
                    FROM agent.user_interest_profiles
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
                version_row = await version_cursor.fetchone()
                profile_version = int(version_row["next_version"])
                await connection.execute(
                    """
                    UPDATE agent.user_interest_profiles
                    SET status = 'retired'
                    WHERE user_id = %s AND status = 'active'
                    """,
                    (user_id,),
                )
                profile_cursor = await connection.execute(
                    """
                    INSERT INTO agent.user_interest_profiles (
                        user_id,
                        version,
                        wiki_version_id,
                        status
                    ) VALUES (%s, %s, %s, 'building')
                    RETURNING id, calculated_at
                    """,
                    (user_id, profile_version, wiki_version_id),
                )
                profile = await profile_cursor.fetchone()
                items: list[dict[str, object]] = []
                for candidate in candidates:
                    interest_cursor = await connection.execute(
                        """
                        INSERT INTO agent.user_interests (
                            profile_id,
                            user_id,
                            topic,
                            category,
                            score,
                            confidence,
                            attributes
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            profile["id"],
                            user_id,
                            candidate.topic,
                            candidate.category,
                            candidate.score,
                            candidate.confidence,
                            Jsonb(candidate.evidence),
                        ),
                    )
                    interest = await interest_cursor.fetchone()
                    for document_id in candidate.document_ids:
                        await connection.execute(
                            """
                            INSERT INTO agent.interest_evidence (
                                interest_id,
                                user_id,
                                document_id,
                                weight,
                                evidence
                            ) VALUES (%s, %s, %s, %s, %s)
                            """,
                            (
                                interest["id"],
                                user_id,
                                document_id,
                                candidate.evidence.get("weight", 1),
                                Jsonb(candidate.evidence),
                            ),
                        )
                    items.append(
                        {
                            "interest_id": str(interest["id"]),
                            "topic": candidate.topic,
                            "category": candidate.category,
                            "score": candidate.score,
                            "confidence": candidate.confidence,
                            "document_ids": list(candidate.document_ids),
                            "evidence": candidate.evidence,
                        }
                    )
                await connection.execute(
                    """
                    UPDATE agent.user_interest_profiles
                    SET status = 'active'
                    WHERE id = %s
                    """,
                    (profile["id"],),
                )
        return {
            "profile_id": str(profile["id"]),
            "user_id": user_id,
            "wiki_version_id": wiki_version_id,
            "version": profile_version,
            "status": "active",
            "calculated_at": profile["calculated_at"],
            "interests": items,
        }

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
                    markdown = _global_article_markdown(article)
                    content_hash = compute_content_hash(markdown)
                    document_key = hashlib.sha256(
                        article.url.encode("utf-8")
                    ).hexdigest()[:24]
                    head_cursor = await connection.execute(
                        """
                        SELECT id, current_version, content_hash
                        FROM agent.wiki_documents
                        WHERE namespace_key = 'global'
                          AND deleted_at IS NULL
                          AND (canonical_url = %s OR content_hash = %s)
                        ORDER BY (canonical_url = %s) DESC, updated_at DESC
                        LIMIT 1
                        FOR UPDATE
                        """,
                        (article.url, content_hash, article.url),
                    )
                    head = await head_cursor.fetchone()
                    if head is None:
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
                            RETURNING id, current_version, content_hash
                            """,
                            (
                                provider,
                                article.url,
                                article.language or "und",
                                content_hash,
                                Jsonb({"provider": provider}),
                                document_key,
                                f"documents/{document_key}.md",
                                article.source_name,
                            ),
                        )
                        head = await insert_cursor.fetchone()
                        if head is None:
                            retry_cursor = await connection.execute(
                                """
                                SELECT id, current_version, content_hash
                                FROM agent.wiki_documents
                                WHERE namespace_key = 'global'
                                  AND deleted_at IS NULL
                                  AND (canonical_url = %s OR content_hash = %s)
                                ORDER BY (canonical_url = %s) DESC, updated_at DESC
                                LIMIT 1
                                FOR UPDATE
                                """,
                                (article.url, content_hash, article.url),
                            )
                            head = await retry_cursor.fetchone()
                            if head is None:
                                raise RuntimeError("Global 문서 Head를 저장하지 못했습니다.")
                    latest_cursor = await connection.execute(
                        """
                        SELECT id, version, content_hash
                        FROM agent.wiki_document_versions
                        WHERE document_id = %s
                        ORDER BY version DESC
                        LIMIT 1
                        FOR UPDATE
                        """,
                        (head["id"],),
                    )
                    latest = await latest_cursor.fetchone()
                    created = latest is None or latest["content_hash"] != content_hash
                    if created:
                        version = int(latest["version"]) + 1 if latest else 1
                        metadata = {
                            "provider": provider,
                            "url": article.url,
                            "published_at": (
                                article.published_at.isoformat()
                                if article.published_at
                                else None
                            ),
                            "source_name": article.source_name,
                            "language": article.language,
                        }
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
                            ) VALUES (%s, 'global', %s, %s, %s, %s, %s, %s)
                            RETURNING id
                            """,
                            (
                                head["id"],
                                version,
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
                        await connection.execute(
                            """
                            UPDATE agent.wiki_documents
                            SET
                                current_version = %s,
                                content_hash = %s,
                                updated_at = clock_timestamp()
                            WHERE id = %s
                            """,
                            (version, content_hash, head["id"]),
                        )
                        document_version_id = str(version_row["id"])
                        created_count += 1
                    else:
                        version = int(latest["version"])
                        document_version_id = str(latest["id"])
                        duplicate_count += 1
                    saved_items.append(
                        {
                            "provider": provider,
                            "title": article.title,
                            "url": article.url,
                            "description": article.description,
                            "published_at": article.published_at,
                            "source_name": article.source_name,
                            "language": article.language,
                            "document_id": str(head["id"]),
                            "document_version_id": document_version_id,
                            "version": version,
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
