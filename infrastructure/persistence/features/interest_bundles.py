"""활성 관심사와 근거 Wiki 노드의 1홉 이웃을 조회하는 저장소 구현."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from psycopg import AsyncConnection

type DictRow = dict[str, Any]

_RELATION_WEIGHT_SQL = """
    CASE relation.relation_type
        WHEN 'entity_relation' THEN 1.0
        WHEN 'applies_concept' THEN 1.0
        WHEN 'related_concept' THEN 0.5
        ELSE 0.0
    END
"""


class ConnectionInterestBundleRepository:
    """열린 PostgreSQL 연결을 INT-012 저장소 경계로 제공한다."""

    def __init__(self, connection: AsyncConnection[DictRow]) -> None:
        """사용자 Scope가 설정된 현재 연결을 보관한다."""
        self._connection = connection

    async def load_active_interest(
        self, user_id: str, interest_id: str
    ) -> Mapping[str, object] | None:
        """현재 활성 Profile에 속한 비차단 관심사와 근거 문서 ID를 조회한다."""
        cursor = await self._connection.execute(
            """
            SELECT
                profile.id::text AS profile_id,
                profile.version AS profile_version,
                interest.topic,
                interest.score::float8 AS score,
                COALESCE(
                    array_agg(DISTINCT evidence.document_id::text)
                        FILTER (WHERE evidence.document_id IS NOT NULL),
                    '{}'
                ) AS document_ids
            FROM agent.user_interest_profiles AS profile
            JOIN agent.user_interests AS interest
              ON interest.profile_id = profile.id
             AND interest.user_id = profile.user_id
            LEFT JOIN agent.interest_evidence AS evidence
              ON evidence.interest_id = interest.id
             AND evidence.user_id = interest.user_id
            WHERE profile.user_id = %s
              AND profile.status = 'active'
              AND interest.id = %s
              AND NOT interest.is_blocked
            GROUP BY profile.id, profile.version, interest.id
            """,
            (user_id, interest_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def list_related_nodes(
        self,
        user_id: str,
        *,
        document_ids: Sequence[str],
        limit: int,
    ) -> Sequence[Mapping[str, object]]:
        """근거 문서 ID에서 양방향 1홉으로 연결된 검색 키워드를 조회한다."""
        if not document_ids or limit <= 0:
            return []
        namespace_key = f"user/{user_id}"
        cursor = await self._connection.execute(
            f"""
            WITH origin AS (
                SELECT document.id, version.id AS version_id
                FROM agent.wiki_documents AS document
                JOIN agent.wiki_document_versions AS version
                  ON version.document_id = document.id
                 AND version.namespace_key = document.namespace_key
                 AND version.version = document.current_version
                WHERE document.id = ANY(%s::uuid[])
                  AND document.namespace_key = %s
                  AND document.document_kind IN ('entity', 'concept')
                  AND document.status = 'active'
                  AND document.deleted_at IS NULL
            )
            SELECT
                peer.id::text AS document_id,
                peer_version.title AS keyword,
                peer.document_kind,
                SUM({_RELATION_WEIGHT_SQL})::float8 AS weight,
                array_agg(DISTINCT relation.relation_type) AS relation_types,
                COALESCE(shared_sources.count, 0)::integer AS shared_source_count,
                COALESCE(peer_relations.degree, 0)::float8 AS degree
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
            LEFT JOIN LATERAL (
                SELECT COUNT(DISTINCT peer_source.source_document_version_id) AS count
                FROM agent.wiki_document_sources AS origin_source
                JOIN origin AS source_origin
                  ON source_origin.version_id = origin_source.wiki_document_version_id
                JOIN agent.wiki_document_sources AS peer_source
                  ON peer_source.source_document_version_id
                     = origin_source.source_document_version_id
                 AND peer_source.wiki_document_version_id = peer_version.id
                WHERE origin_source.namespace_key = %s
                  AND peer_source.namespace_key = %s
            ) AS shared_sources ON true
            LEFT JOIN LATERAL (
                SELECT SUM(
                    CASE peer_relation.relation_type
                        WHEN 'entity_relation' THEN 1.0
                        WHEN 'applies_concept' THEN 1.0
                        WHEN 'related_concept' THEN 0.5
                        ELSE 0.0
                    END
                ) AS degree
                FROM agent.wiki_document_relations AS peer_relation
                JOIN agent.wiki_documents AS active_peer
                  ON active_peer.id = CASE
                         WHEN peer_relation.source_document_id = peer.id
                         THEN peer_relation.target_document_id
                         ELSE peer_relation.source_document_id
                     END
                 AND active_peer.namespace_key = peer_relation.namespace_key
                WHERE peer.id IN (
                    peer_relation.source_document_id,
                    peer_relation.target_document_id
                )
                  AND peer_relation.namespace_key = %s
                  AND active_peer.status = 'active'
                  AND active_peer.deleted_at IS NULL
            ) AS peer_relations ON true
            WHERE relation.namespace_key = %s
              AND peer.document_kind IN ('entity', 'concept')
              AND peer.status = 'active'
              AND peer.deleted_at IS NULL
              AND COALESCE(peer.domain, '') <> 'organization'
              AND peer.id NOT IN (SELECT id FROM origin)
            GROUP BY
                peer.id,
                peer_version.title,
                peer.document_kind,
                shared_sources.count,
                peer_relations.degree
            HAVING SUM({_RELATION_WEIGHT_SQL}) > 0
            ORDER BY
                weight DESC,
                shared_source_count DESC,
                degree DESC,
                keyword ASC
            LIMIT %s
            """,
            (
                list(document_ids),
                namespace_key,
                namespace_key,
                namespace_key,
                namespace_key,
                namespace_key,
                limit,
            ),
        )
        return [dict(row) for row in await cursor.fetchall()]
