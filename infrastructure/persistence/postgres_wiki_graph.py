"""PostgreSQL 기반 개인 Wiki Graph 조회 저장소.

사용자 RLS Scope 안에서 현재 Entity·Concept Head와 최신 Version,
wiki_document_relations를 읽어 Obsidian 스타일 Graph 응답으로 조립한다.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

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
