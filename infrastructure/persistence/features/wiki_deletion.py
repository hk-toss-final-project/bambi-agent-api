"""사용자 요청에 의한 개인 Wiki 문서 삭제 반영 기능 구현.

delete 이벤트를 기록하고 대상 문서를 soft-delete하며, 파생 Chunk를 검색에서
제외한다. 관계 Row는 지우지 않는다 — 조회가 deleted 문서를 걸러내므로
자동으로 숨겨지고, 같은 개념이 새 클리핑으로 재등장하면 새 문서로 되살아난다
(D1 잠정 결정: 기본 부활, tombstone 없음 — 팀 확정 시 억제 옵션 추가).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from infrastructure.persistence.features.personal_wiki import set_personal_wiki_scope

type DictRow = dict[str, Any]


class WikiDocumentNotFoundError(Exception):
    """삭제 대상 Wiki 문서를 찾을 수 없을 때 발생하는 저장소 오류."""

    def __init__(self, document_id: str) -> None:
        """찾지 못한 문서 식별자를 보관한다."""
        super().__init__(f"Wiki 문서를 찾을 수 없습니다: {document_id}")
        self.document_id = document_id


async def delete_wiki_document_and_record_event(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    document_id: str,
    source_event_id: str,
    occurred_at: datetime | None,
    memo: str | None,
) -> dict[str, object]:
    """delete 이벤트를 기록하고 Wiki 문서를 soft-delete한다.

    이미 삭제된 문서에 대한 재요청은 오류가 아니라 `already_deleted=True`로
    멱등 처리한다. Chunk는 is_searchable=false로 전환되어 검색·RAG에서
    즉시 제외된다.

    Raises:
        WikiDocumentNotFoundError: 사용자 Namespace에 해당 문서가 없는 경우
    """
    namespace_key = f"user/{user_id}"
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        existing_cursor = await connection.execute(
            """
            SELECT id, document_kind, document_key, deleted_at
            FROM agent.wiki_documents
            WHERE id::text = %s AND namespace_key = %s
            FOR UPDATE
            """,
            (document_id, namespace_key),
        )
        existing = await existing_cursor.fetchone()
        if existing is None:
            raise WikiDocumentNotFoundError(document_id)
        await connection.execute(
            """
            INSERT INTO agent.wiki_source_events (
                user_id,
                source_event_id,
                source_type,
                occurred_at,
                object_uri,
                payload,
                status
            ) VALUES (
                %s, %s, 'delete', COALESCE(%s, clock_timestamp()),
                %s, %s, 'completed'
            )
            ON CONFLICT (user_id, source_event_id) DO NOTHING
            """,
            (
                user_id,
                source_event_id,
                occurred_at,
                str(existing["id"]),
                Jsonb(
                    {
                        "document_id": str(existing["id"]),
                        "document_kind": existing["document_kind"],
                        "document_key": existing["document_key"],
                        "memo": memo,
                    }
                ),
            ),
        )
        already_deleted = existing["deleted_at"] is not None
        unsearchable_count = 0
        if not already_deleted:
            await connection.execute(
                """
                UPDATE agent.wiki_documents
                SET status = 'deleted',
                    deleted_at = clock_timestamp(),
                    updated_at = clock_timestamp()
                WHERE id = %s AND namespace_key = %s
                """,
                (existing["id"], namespace_key),
            )
            chunk_cursor = await connection.execute(
                """
                UPDATE agent.wiki_chunks
                SET is_searchable = false
                WHERE namespace_key = %s
                  AND document_version_id IN (
                      SELECT id
                      FROM agent.wiki_document_versions
                      WHERE document_id = %s AND namespace_key = %s
                  )
                RETURNING id
                """,
                (namespace_key, existing["id"], namespace_key),
            )
            unsearchable_count = len(await chunk_cursor.fetchall())
    return {
        "document_id": str(existing["id"]),
        "document_kind": str(existing["document_kind"]),
        "document_key": str(existing["document_key"]),
        "already_deleted": already_deleted,
        "unsearchable_chunk_count": unsearchable_count,
    }
