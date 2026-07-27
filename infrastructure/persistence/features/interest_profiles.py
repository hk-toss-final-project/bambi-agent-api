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
    """활성 Wiki Build와 관심 키워드 계산에 사용할 현재 문서를 조회한다.

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
