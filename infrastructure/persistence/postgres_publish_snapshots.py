"""PostgreSQL 기반 Publish Snapshot 저장소.

개발 Seed와 실제 Worker가 저장한 Snapshot을 Service Worker API에 제공하고,
발행 ACK를 Snapshot 상태 및 시도 이력과 같은 트랜잭션으로 기록한다.
"""

from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from app.schemas.mvp import PublishAckRequest, PublishSnapshotResponse
from app.services.publish_snapshots import (
    PublishSnapshotMismatchError,
    PublishSnapshotNotFoundError,
    StalePublishSnapshotError,
)

type DictRow = dict[str, Any]


class PostgresPublishSnapshotRepository:
    """PostgreSQL에서 Publish Snapshot과 발행 ACK를 관리한다."""

    def __init__(self, database_url: str) -> None:
        """지연 시작 방식의 PostgreSQL 연결 Pool을 구성한다."""
        self._pool: AsyncConnectionPool[DictRow] = AsyncConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=4,
            open=False,
            kwargs={"row_factory": dict_row},
        )

    async def startup(self) -> None:
        """연결 Pool을 열고 최소 연결이 준비될 때까지 기다린다."""
        await self._pool.open(wait=True)

    async def shutdown(self) -> None:
        """사용 중인 PostgreSQL 연결 Pool을 안전하게 종료한다."""
        await self._pool.close()

    @staticmethod
    async def _set_system_scope(connection: AsyncConnection[DictRow]) -> None:
        """Service Worker 조회·ACK 트랜잭션에 시스템 RLS Scope를 설정한다."""
        await connection.execute("SET LOCAL app.access_scope = 'system'")

    async def save(self, snapshot: PublishSnapshotResponse) -> None:
        """생성 후보와 연결된 새로운 Publish Snapshot 버전을 저장한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await self._set_system_scope(connection)
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (snapshot.content_id,),
                )
                latest_cursor = await connection.execute(
                    """
                    SELECT version
                    FROM agent.publish_snapshots
                    WHERE content_id = %s
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (snapshot.content_id,),
                )
                latest = await latest_cursor.fetchone()
                if latest and snapshot.version <= latest["version"]:
                    raise StalePublishSnapshotError(snapshot.content_id)

                candidate_cursor = await connection.execute(
                    """
                    SELECT id, user_id, snapshot_hash
                    FROM agent.generated_content_candidates
                    WHERE content_id = %s AND version = %s
                    """,
                    (snapshot.content_id, snapshot.version),
                )
                candidate = await candidate_cursor.fetchone()
                if candidate is None:
                    raise PublishSnapshotNotFoundError(snapshot.content_id)
                if (
                    candidate["user_id"] != snapshot.user_id
                    or candidate["snapshot_hash"] != snapshot.snapshot_hash
                ):
                    raise PublishSnapshotMismatchError(snapshot.content_id)

                content_payload = {
                    "title": snapshot.title,
                    "summary": snapshot.summary,
                    "body": snapshot.body,
                    "citations": [
                        citation.model_dump(mode="json")
                        for citation in snapshot.citations
                    ],
                }
                await connection.execute(
                    """
                    INSERT INTO agent.publish_snapshots (
                        candidate_id,
                        user_id,
                        content_id,
                        version,
                        snapshot_hash,
                        payload,
                        status,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'ready', %s)
                    """,
                    (
                        candidate["id"],
                        snapshot.user_id,
                        snapshot.content_id,
                        snapshot.version,
                        snapshot.snapshot_hash,
                        Jsonb(content_payload),
                        snapshot.created_at,
                    ),
                )

    async def get_latest(self, content_id: str) -> PublishSnapshotResponse | None:
        """콘텐츠 식별자의 최신 Publish Snapshot을 PostgreSQL에서 조회한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await self._set_system_scope(connection)
                cursor = await connection.execute(
                    """
                    SELECT
                        user_id,
                        content_id,
                        version,
                        snapshot_hash,
                        payload,
                        created_at
                    FROM agent.publish_snapshots
                    WHERE content_id = %s
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (content_id,),
                )
                row = await cursor.fetchone()
        if row is None:
            return None
        payload = row["payload"]
        return PublishSnapshotResponse.model_validate(
            {
                "content_id": row["content_id"],
                "user_id": row["user_id"],
                "version": row["version"],
                "snapshot_hash": row["snapshot_hash"],
                "title": payload["title"],
                "summary": payload["summary"],
                "body": payload["body"],
                "citations": payload.get("citations", []),
                "created_at": row["created_at"],
            }
        )

    async def acknowledge(
        self, content_id: str, payload: PublishAckRequest
    ) -> datetime:
        """최신 Snapshot 검증과 ACK 이력 저장을 하나의 트랜잭션으로 처리한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await self._set_system_scope(connection)
                snapshot_cursor = await connection.execute(
                    """
                    SELECT id, user_id, version, snapshot_hash
                    FROM agent.publish_snapshots
                    WHERE content_id = %s
                    ORDER BY version DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (content_id,),
                )
                snapshot = await snapshot_cursor.fetchone()
                if snapshot is None:
                    raise PublishSnapshotNotFoundError(content_id)
                if (
                    snapshot["version"] != payload.version
                    or snapshot["snapshot_hash"] != payload.snapshot_hash
                ):
                    raise PublishSnapshotMismatchError(content_id)

                attempt_cursor = await connection.execute(
                    """
                    SELECT COALESCE(MAX(attempt_number), 0) + 1 AS attempt_number
                    FROM agent.publish_attempts
                    WHERE snapshot_id = %s
                    """,
                    (snapshot["id"],),
                )
                attempt = await attempt_cursor.fetchone()
                update_cursor = await connection.execute(
                    """
                    UPDATE agent.publish_snapshots
                    SET
                        status = %s,
                        acknowledged_at = clock_timestamp(),
                        failure_reason = %s
                    WHERE id = %s
                    RETURNING acknowledged_at
                    """,
                    (
                        payload.status.value,
                        payload.failure_reason,
                        snapshot["id"],
                    ),
                )
                updated = await update_cursor.fetchone()
                await connection.execute(
                    """
                    INSERT INTO agent.publish_attempts (
                        snapshot_id,
                        user_id,
                        attempt_number,
                        status,
                        failure_reason,
                        acknowledged_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        snapshot["id"],
                        snapshot["user_id"],
                        attempt["attempt_number"],
                        payload.status.value,
                        payload.failure_reason,
                        updated["acknowledged_at"],
                    ),
                )
                return updated["acknowledged_at"]
