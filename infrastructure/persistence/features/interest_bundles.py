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

    async def find_active_interest_id(
        self, user_id: str, topic: str
    ) -> str | None:
        """주제 문자열과 대소문자 무시 일치하는 활성·비차단 관심사 ID를 찾는다.

        일치가 여러 건이면 점수가 가장 높은 관심사 하나만 반환한다.
        """
        cursor = await self._connection.execute(
            """
            SELECT interest.id::text AS interest_id
            FROM agent.user_interest_profiles AS profile
            JOIN agent.user_interests AS interest
              ON interest.profile_id = profile.id
             AND interest.user_id = profile.user_id
            WHERE profile.user_id = %s
              AND profile.status = 'active'
              AND NOT interest.is_blocked
              AND lower(interest.topic) = lower(%s)
            ORDER BY interest.score DESC
            LIMIT 1
            """,
            (user_id, topic),
        )
        row = await cursor.fetchone()
        return str(row["interest_id"]) if row is not None else None

    async def list_node_snapshots(
        self,
        user_id: str,
        *,
        document_ids: Sequence[str],
    ) -> Sequence[Mapping[str, object]]:
        """관심 근거 노드의 현재 Version·요약·별칭을 입력 순서대로 조회한다."""
        if not document_ids:
            return []
        namespace_key = f"user/{user_id}"
        cursor = await self._connection.execute(
            """
            SELECT
                document.id::text AS document_id,
                version.id::text AS document_version_id,
                version.title AS keyword,
                document.document_kind,
                COALESCE(version.summary, '') AS summary,
                CASE
                    WHEN jsonb_typeof(version.source_metadata -> 'aliases') = 'array'
                    THEN ARRAY(
                        SELECT jsonb_array_elements_text(
                            version.source_metadata -> 'aliases'
                        )
                    )
                    ELSE ARRAY[]::text[]
                END AS aliases,
                version.created_at AS updated_at
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
            ORDER BY array_position(%s::uuid[], document.id)
            """,
            (list(document_ids), namespace_key, list(document_ids)),
        )
        return [dict(row) for row in await cursor.fetchall()]

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
            ),
            raw_neighbor_relations AS (
                SELECT
                    origin.id AS origin_id,
                    peer.id AS peer_id,
                    relation.id AS relation_id,
                    relation.source_document_id,
                    relation.target_document_id,
                    relation.relation_type,
                    relation.confidence::float8 AS confidence,
                    relation.provenance_kind,
                    relation.review_status,
                    COALESCE(relation.metadata ->> 'rationale', '') AS rationale,
                    active_supports.items AS supports,
                    {_RELATION_WEIGHT_SQL} AS weight
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
                JOIN LATERAL (
                    SELECT jsonb_agg(
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
                        ORDER BY
                            CASE support.review_status
                                WHEN 'accepted' THEN 0
                                ELSE 1
                            END,
                            support.confidence DESC,
                            support.updated_at DESC,
                            support.id
                    ) AS items
                    FROM (
                        SELECT candidate.*
                        FROM agent.wiki_relation_supports AS candidate
                        WHERE candidate.relation_id = relation.id
                          AND candidate.namespace_key = relation.namespace_key
                          AND candidate.status = 'active'
                          AND candidate.review_status <> 'rejected'
                        ORDER BY
                            CASE candidate.review_status
                                WHEN 'accepted' THEN 0
                                ELSE 1
                            END,
                            candidate.confidence DESC,
                            candidate.updated_at DESC,
                            candidate.id
                        LIMIT 3
                    ) AS support
                ) AS active_supports ON active_supports.items IS NOT NULL
                WHERE relation.namespace_key = %s
                  AND relation.status = 'active'
                  AND relation.review_status <> 'rejected'
                  AND peer.document_kind IN ('entity', 'concept')
                  AND peer.status = 'active'
                  AND peer.deleted_at IS NULL
                  AND COALESCE(peer.domain, '') <> 'organization'
                  AND peer.id NOT IN (SELECT id FROM origin)
            ),
            neighbor_pairs AS (
                SELECT origin_id, peer_id, MAX(weight) AS max_weight
                FROM raw_neighbor_relations
                GROUP BY origin_id, peer_id
            ),
            neighbor_scores AS (
                SELECT peer_id, SUM(max_weight)::float8 AS weight
                FROM neighbor_pairs
                GROUP BY peer_id
            ),
            neighbor_relation_types AS (
                SELECT
                    peer_id,
                    array_agg(DISTINCT relation_type ORDER BY relation_type)
                        AS relation_types
                FROM raw_neighbor_relations
                GROUP BY peer_id
            ),
            neighbor_relation_details AS (
                SELECT
                    peer_id,
                    jsonb_agg(
                        jsonb_build_object(
                            'relation_id', relation_id::text,
                            'root_document_id', origin_id::text,
                            'direction', CASE
                                WHEN source_document_id = origin_id
                                THEN 'root_to_neighbor'
                                ELSE 'neighbor_to_root'
                            END,
                            'relation_type', relation_type,
                            'confidence', confidence,
                            'provenance_kind', provenance_kind,
                            'review_status', review_status,
                            'rationale', rationale,
                            'supports', supports
                        )
                        ORDER BY origin_id::text, relation_type, relation_id::text
                    ) AS relations
                FROM raw_neighbor_relations
                GROUP BY peer_id
            )
            SELECT
                peer.id::text AS document_id,
                peer_version.id::text AS document_version_id,
                peer_version.title AS keyword,
                peer.document_kind,
                COALESCE(peer_version.summary, '') AS summary,
                CASE
                    WHEN jsonb_typeof(
                        peer_version.source_metadata -> 'aliases'
                    ) = 'array'
                    THEN ARRAY(
                        SELECT jsonb_array_elements_text(
                            peer_version.source_metadata -> 'aliases'
                        )
                    )
                    ELSE ARRAY[]::text[]
                END AS aliases,
                peer_version.created_at AS updated_at,
                neighbor_scores.weight,
                neighbor_relation_types.relation_types,
                neighbor_relation_details.relations,
                COALESCE(shared_sources.count, 0)::integer AS shared_source_count,
                COALESCE(peer_relations.degree, 0)::float8 AS degree
            FROM neighbor_scores
            JOIN agent.wiki_documents AS peer
              ON peer.id = neighbor_scores.peer_id
             AND peer.namespace_key = %s
            JOIN agent.wiki_document_versions AS peer_version
              ON peer_version.document_id = peer.id
             AND peer_version.namespace_key = peer.namespace_key
             AND peer_version.version = peer.current_version
            JOIN neighbor_relation_types
              ON neighbor_relation_types.peer_id = peer.id
            JOIN neighbor_relation_details
              ON neighbor_relation_details.peer_id = peer.id
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
                SELECT SUM(neighbor.max_weight) AS degree
                FROM (
                    SELECT
                        active_peer.id,
                        MAX(
                            CASE peer_relation.relation_type
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
                        ) AS max_weight
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
                      AND peer_relation.status = 'active'
                      AND peer_relation.review_status <> 'rejected'
                      AND active_peer.status = 'active'
                      AND active_peer.deleted_at IS NULL
                    GROUP BY active_peer.id
                ) AS neighbor
            ) AS peer_relations ON true
            WHERE peer.document_kind IN ('entity', 'concept')
              AND peer.status = 'active'
              AND peer.deleted_at IS NULL
              AND COALESCE(peer.domain, '') <> 'organization'
              AND neighbor_scores.weight > 0
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
                namespace_key,
                limit,
            ),
        )
        return [dict(row) for row in await cursor.fetchall()]
