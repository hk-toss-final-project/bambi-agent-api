"""관심사 프로필 영속화의 커넥션 단위 기능 구현.

PostgresWikiGraphRepository(자체 Pool 소유)와 Wiki Build 완료 재계산 훅
(agent.graph.run_personal_wiki_build — Worker·개발 API가 공유하는 커넥션 사용)이
같은 조회·저장 SQL을 쓰도록, 관심사 프로필 로직을 커넥션 함수로 제공한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from infrastructure.persistence.features.personal_wiki import set_personal_wiki_scope
from shared.wiki_models import InterestCandidate

type DictRow = dict[str, Any]


async def load_interest_documents_for_user(
    connection: AsyncConnection[DictRow], *, user_id: str
) -> Mapping[str, object]:
    """활성 Wiki Build와 관심 키워드 계산에 쓸 Entity·Concept 노드를 조회한다.

    노드마다 관계 유형을 가중한 연결 수(degree), 근거 원문의 수·종류와
    최신 활동 시각을 함께 계산해 INT-001·INT-005 입력으로 넘긴다.

    Args:
        connection: 이미 열린 agent-db 커넥션 (조회 Transaction은 내부에서 연다)
        user_id: 관심사를 계산할 사용자 ID

    Returns:
        활성 Wiki Version 정보와 현재 문서 Row 목록
    """
    namespace_key = f"user/{user_id}"
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
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
                version.source_metadata,
                COALESCE(relation_stats.degree, 0)::float8 AS degree,
                COALESCE(source_stats.source_count, 0) AS source_count,
                COALESCE(
                    source_stats.source_types, ARRAY[]::text[]
                ) AS source_types,
                COALESCE(
                    source_stats.last_source_at, document.updated_at
                ) AS last_activity_at
            FROM agent.wiki_documents AS document
            JOIN agent.wiki_document_versions AS version
              ON version.document_id = document.id
             AND version.namespace_key = document.namespace_key
             AND version.version = document.current_version
            LEFT JOIN LATERAL (
                SELECT SUM(
                    CASE relation.relation_type
                        WHEN 'entity_relation' THEN 1.0
                        WHEN 'applies_concept' THEN 1.0
                        WHEN 'related_concept' THEN 0.5
                        ELSE 0.0
                    END
                ) AS degree
                FROM agent.wiki_document_relations AS relation
                JOIN agent.wiki_documents AS peer
                  ON peer.id = CASE
                         WHEN relation.source_document_id = document.id
                         THEN relation.target_document_id
                         ELSE relation.source_document_id
                     END
                 AND peer.namespace_key = relation.namespace_key
                WHERE relation.namespace_key = document.namespace_key
                  AND document.id IN (
                      relation.source_document_id,
                      relation.target_document_id
                  )
                  AND peer.document_kind IN ('entity', 'concept')
                  AND peer.status = 'active'
                  AND peer.deleted_at IS NULL
            ) AS relation_stats ON true
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(DISTINCT source_document.id) AS source_count,
                    array_agg(
                        DISTINCT source_document.source_type
                    ) AS source_types,
                    MAX(
                        COALESCE(
                            source_version.clipped_on::timestamptz,
                            source_version.created_at
                        )
                    ) AS last_source_at
                FROM agent.wiki_document_sources AS link
                JOIN agent.user_source_document_versions AS source_version
                  ON source_version.id = link.source_document_version_id
                 AND source_version.namespace_key = link.namespace_key
                JOIN agent.user_source_documents AS source_document
                  ON source_document.id = source_version.source_document_id
                 AND source_document.namespace_key
                     = source_version.namespace_key
                WHERE link.wiki_document_version_id = version.id
            ) AS source_stats ON true
            WHERE document.namespace_key = %s
              AND document.document_kind IN ('entity', 'concept')
              AND document.status = 'active'
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
                "degree": float(document["degree"]),
                "source_count": int(document["source_count"]),
                "source_types": list(document["source_types"] or []),
            }
            for document in documents
        ],
    }


async def save_interest_profile_for_user(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    wiki_version_id: str,
    candidates: Sequence[InterestCandidate],
) -> Mapping[str, object]:
    """계산된 관심 후보를 새 Profile Version과 근거 Row로 저장한다.

    기존 active Profile을 retired로 전환하고 새 Version을 active로 만든다.
    사용자 단위 advisory lock으로 동시 재계산을 직렬화한다.

    Args:
        connection: 이미 열린 agent-db 커넥션 (저장 Transaction은 내부에서 연다)
        user_id: 대상 사용자 ID
        wiki_version_id: 계산 기준이 된 활성 Wiki Version ID
        candidates: INT-001이 계산한 관심 후보 목록

    Returns:
        저장된 활성 관심 Profile Payload
    """
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
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


# 행동 신호 조회 기본값 — 반감기 14일(D2 잠정) 기준으로 충분히 넓은 창.
_FEEDBACK_LOOKBACK_DAYS = 30
_FEEDBACK_EVENT_LIMIT = 500


async def load_recent_feedback_signals_for_user(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    lookback_days: int = _FEEDBACK_LOOKBACK_DAYS,
) -> list[dict[str, object]]:
    """최근 feedback 이벤트를 Topic 단위 행동 신호로 평탄화해 반환한다.

    이벤트 payload의 `topics` 목록을 펼쳐 `{topic, signal_type, occurred_at}`
    신호로 만든다 — INT-005 점수 보정의 입력이다.
    """
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        cursor = await connection.execute(
            """
            SELECT payload, occurred_at
            FROM agent.wiki_source_events
            WHERE user_id = %s
              AND source_type = 'feedback'
              AND occurred_at >= clock_timestamp() - make_interval(days => %s)
            ORDER BY occurred_at DESC
            LIMIT %s
            """,
            (user_id, lookback_days, _FEEDBACK_EVENT_LIMIT),
        )
        rows = await cursor.fetchall()
    signals: list[dict[str, object]] = []
    for row in rows:
        payload = dict(row["payload"] or {})
        signal_type = str(payload.get("signal_type") or "")
        topics = payload.get("topics")
        if not signal_type or not isinstance(topics, list):
            continue
        for topic in topics:
            value = str(topic or "").strip()
            if value:
                signals.append(
                    {
                        "topic": value,
                        "signal_type": signal_type,
                        "occurred_at": row["occurred_at"],
                    }
                )
    return signals


async def save_feedback_signals_for_user(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    signals: Sequence[Mapping[str, object]],
) -> int:
    """행동 신호를 feedback 이벤트로 멱등 저장하고 신규 저장 수를 반환한다.

    신호는 Wiki 문서를 만들지 않고 이벤트로만 남으며(SVC-006), 다음 관심사
    재계산(INT-011) 때 INT-005가 읽어 점수에 반영한다. `source_event_id`
    중복은 건너뛴다.
    """
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        accepted = 0
        for signal in signals:
            payload = {
                "signal_type": str(signal.get("signal_type") or ""),
                "topics": [
                    str(topic).strip()
                    for topic in (signal.get("topics") or [])
                    if str(topic).strip()
                ],
                "content_id": signal.get("content_id"),
            }
            cursor = await connection.execute(
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
                    %s, %s, 'feedback', COALESCE(%s, clock_timestamp()),
                    %s, %s, 'completed'
                )
                ON CONFLICT (user_id, source_event_id) DO NOTHING
                RETURNING id
                """,
                (
                    user_id,
                    str(signal.get("source_event_id") or ""),
                    signal.get("occurred_at"),
                    (
                        str(signal["content_id"])
                        if signal.get("content_id")
                        else None
                    ),
                    Jsonb(payload),
                ),
            )
            if await cursor.fetchone() is not None:
                accepted += 1
    return accepted


class ConnectionInterestProfileRepository:
    """이미 열린 커넥션 위에서 관심사 재계산(INT-011) 저장소 계약을 제공한다.

    Wiki Build 완료 훅처럼 Worker·개발 API가 소유한 커넥션을 그대로 재사용해야
    하는 호출자를 위한 어댑터다. domain.interests의 InterestProfileRepository
    Protocol을 만족한다.
    """

    def __init__(self, connection: AsyncConnection[DictRow]) -> None:
        """재계산에 사용할 열린 커넥션을 주입한다."""
        self._connection = connection

    async def load_interest_documents(self, user_id: str) -> Mapping[str, object]:
        """활성 Wiki Build와 현재 Wiki 문서를 반환한다."""
        return await load_interest_documents_for_user(
            self._connection, user_id=user_id
        )

    async def save_interest_profile(
        self,
        user_id: str,
        *,
        wiki_version_id: str,
        candidates: Sequence[InterestCandidate],
    ) -> Mapping[str, object]:
        """새 관심 Profile Version과 근거를 저장한다."""
        return await save_interest_profile_for_user(
            self._connection,
            user_id=user_id,
            wiki_version_id=wiki_version_id,
            candidates=candidates,
        )

    async def load_recent_feedback_signals(
        self, user_id: str
    ) -> list[dict[str, object]]:
        """최근 사용자 행동 신호를 Topic 단위로 반환한다."""
        return await load_recent_feedback_signals_for_user(
            self._connection, user_id=user_id
        )
