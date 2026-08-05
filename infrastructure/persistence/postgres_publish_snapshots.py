"""PostgreSQL 기반 Publish Snapshot 저장소.

개발 Seed와 실제 Worker가 저장한 Snapshot을 Service Worker API에 제공하고,
발행 ACK를 Snapshot 상태 및 시도 이력과 같은 트랜잭션으로 기록한다.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from app.schemas.mvp import (
    PublishAckRequest,
    PublishBatchAckItemRequest,
    PublishBatchAckItemResponse,
    PublishBatchAckRequest,
    PublishBatchAckResponse,
    PublishBatchClaimRequest,
    PublishBatchClaimResponse,
    PublishBatchResultStatus,
    PublishSnapshotResponse,
    PublishStatus,
)
from app.services.publish_snapshots import (
    MAX_PUBLISH_ATTEMPTS,
    PublishBatchLeaseExpiredError,
    PublishBatchNotFoundError,
    PublishBatchOwnershipMismatchError,
    PublishSnapshotMismatchError,
    PublishSnapshotNotFoundError,
    StalePublishSnapshotError,
    build_batch_ack_response,
    publish_retry_delay,
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

    @staticmethod
    def _snapshot_from_row(row: DictRow) -> PublishSnapshotResponse:
        """PostgreSQL 조회 Row를 Publish Snapshot 응답으로 변환한다."""
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
                # 아래 셋은 나중에 추가된 필드라, 그 전에 저장된 Snapshot에는 없다.
                # 쓰는 쪽(generation_runtime.persist_report_generation)에 필드를
                # 추가할 때 이 매핑도 함께 고쳐야 한다 — 여기서 키를 명시적으로
                # 고르므로 payload에만 넣으면 응답에 나오지 않는다
                # (2026-08-05 실측: content_tags가 저장은 됐는데 응답이 늘 빈 목록).
                "generation_topic": payload.get("generation_topic", ""),
                "tags": payload.get("tags", []),
                "content_tags": payload.get("content_tags", []),
                "created_at": row["created_at"],
            }
        )

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
        return self._snapshot_from_row(row)

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
                        claim_id = NULL,
                        claimed_by = NULL,
                        lease_expires_at = NULL,
                        next_attempt_at = NULL,
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

    async def claim_batch(
        self, payload: PublishBatchClaimRequest
    ) -> PublishBatchClaimResponse:
        """처리 가능한 Snapshot을 짧은 트랜잭션에서 Lease와 함께 점유한다."""
        batch_id = uuid4()
        now = datetime.now(UTC)
        lease_expires_at = now + timedelta(seconds=payload.lease_seconds)
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await self._set_system_scope(connection)
                cursor = await connection.execute(
                    """
                    WITH eligible AS (
                        SELECT id
                        FROM agent.publish_snapshots
                        WHERE (
                            status = 'ready'
                            AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
                        ) OR (
                            status = 'claimed'
                            AND lease_expires_at IS NOT NULL
                            AND lease_expires_at <= %s
                        )
                        ORDER BY created_at, id
                        FOR UPDATE SKIP LOCKED
                        LIMIT %s
                    )
                    UPDATE agent.publish_snapshots AS snapshot
                    SET
                        status = 'claimed',
                        claim_id = %s,
                        claimed_by = %s,
                        lease_expires_at = %s,
                        attempt_count = snapshot.attempt_count + 1,
                        next_attempt_at = NULL,
                        acknowledged_at = NULL,
                        failure_reason = NULL
                    FROM eligible
                    WHERE snapshot.id = eligible.id
                    RETURNING
                        snapshot.id,
                        snapshot.user_id,
                        snapshot.content_id,
                        snapshot.version,
                        snapshot.snapshot_hash,
                        snapshot.payload,
                        snapshot.created_at,
                        snapshot.attempt_count
                    """,
                    (
                        now,
                        now,
                        payload.limit,
                        batch_id,
                        payload.worker_id,
                        lease_expires_at,
                    ),
                )
                rows = await cursor.fetchall()
                rows.sort(key=lambda row: (row["created_at"], str(row["id"])))
                for row in rows:
                    await connection.execute(
                        """
                        INSERT INTO agent.publish_attempts (
                            snapshot_id,
                            user_id,
                            attempt_number,
                            worker_event_id,
                            status,
                            claim_id,
                            claimed_by,
                            lease_expires_at
                        ) VALUES (%s, %s, %s, %s, 'requested', %s, %s, %s)
                        """,
                        (
                            row["id"],
                            row["user_id"],
                            row["attempt_count"],
                            f"batch:{batch_id}",
                            batch_id,
                            payload.worker_id,
                            lease_expires_at,
                        ),
                    )

        if not rows:
            return PublishBatchClaimResponse(worker_id=payload.worker_id)
        return PublishBatchClaimResponse(
            batch_id=str(batch_id),
            worker_id=payload.worker_id,
            lease_expires_at=lease_expires_at,
            items=[self._snapshot_from_row(row) for row in rows],
        )

    async def acknowledge_batch(
        self, batch_id: str, payload: PublishBatchAckRequest
    ) -> PublishBatchAckResponse:
        """Batch Claim의 소유권을 검증하고 항목별 결과를 멱등하게 기록한다."""
        now = datetime.now(UTC)
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await self._set_system_scope(connection)
                attempts = await self._get_batch_attempts(connection, batch_id)
                if not attempts:
                    raise PublishBatchNotFoundError(batch_id)
                if any(
                    attempt["claimed_by"] != payload.worker_id
                    for attempt in attempts
                ):
                    raise PublishBatchOwnershipMismatchError(batch_id)

                attempts_by_item = {
                    (attempt["content_id"], attempt["version"]): attempt
                    for attempt in attempts
                }
                cached_results = self._cached_results(payload, attempts_by_item)
                if len(cached_results) == len(payload.items):
                    acknowledged_at = max(
                        attempts_by_item[(item.content_id, item.version)][
                            "attempt_acknowledged_at"
                        ]
                        for item in payload.items
                    )
                    return build_batch_ack_response(
                        batch_id, cached_results, acknowledged_at
                    )

                lease_expires_at = attempts[0]["attempt_lease_expires_at"]
                if lease_expires_at <= now:
                    raise PublishBatchLeaseExpiredError(batch_id)

                results: list[PublishBatchAckItemResponse] = []
                for item in payload.items:
                    attempt = attempts_by_item.get((item.content_id, item.version))
                    if attempt is None or attempt["snapshot_hash"] != item.snapshot_hash:
                        raise PublishSnapshotMismatchError(item.content_id)
                    if attempt["attempt_status"] != "requested":
                        results.append(self._result_from_attempt(attempt))
                        continue
                    if (
                        str(attempt["snapshot_claim_id"]) != batch_id
                        or attempt["snapshot_status"] != "claimed"
                    ):
                        raise PublishSnapshotMismatchError(item.content_id)

                    result = await self._acknowledge_batch_item(
                        connection, attempt, item, now
                    )
                    results.append(result)

                return build_batch_ack_response(batch_id, results, now)

    async def _get_batch_attempts(
        self, connection: AsyncConnection[DictRow], batch_id: str
    ) -> list[DictRow]:
        """Batch ID에 연결된 발행 시도와 현재 Snapshot 상태를 잠금 조회한다."""
        cursor = await connection.execute(
            """
            SELECT
                attempt.id AS attempt_id,
                attempt.status AS attempt_status,
                attempt.retryable AS attempt_retryable,
                attempt.failure_reason AS attempt_failure_reason,
                attempt.acknowledged_at AS attempt_acknowledged_at,
                attempt.claimed_by,
                attempt.lease_expires_at AS attempt_lease_expires_at,
                snapshot.id AS snapshot_id,
                snapshot.user_id,
                snapshot.content_id,
                snapshot.version,
                snapshot.snapshot_hash,
                snapshot.status AS snapshot_status,
                snapshot.claim_id AS snapshot_claim_id,
                snapshot.attempt_count
            FROM agent.publish_attempts AS attempt
            JOIN agent.publish_snapshots AS snapshot
              ON snapshot.id = attempt.snapshot_id
            WHERE attempt.claim_id = %s
            ORDER BY snapshot.created_at, snapshot.id
            FOR UPDATE OF attempt, snapshot
            """,
            (batch_id,),
        )
        return list(await cursor.fetchall())

    def _cached_results(
        self,
        payload: PublishBatchAckRequest,
        attempts_by_item: dict[tuple[str, int], DictRow],
    ) -> list[PublishBatchAckItemResponse]:
        """이미 처리된 ACK 항목의 기존 결과를 요청 순서대로 반환한다."""
        results: list[PublishBatchAckItemResponse] = []
        for item in payload.items:
            attempt = attempts_by_item.get((item.content_id, item.version))
            if attempt is None or attempt["snapshot_hash"] != item.snapshot_hash:
                raise PublishSnapshotMismatchError(item.content_id)
            if attempt["attempt_status"] == "requested":
                continue
            if (
                item.status is PublishStatus.PUBLISHED
                and attempt["attempt_status"] != "published"
            ) or (
                item.status is PublishStatus.FAILED
                and attempt["attempt_status"] != "failed"
            ):
                raise PublishSnapshotMismatchError(item.content_id)
            results.append(self._result_from_attempt(attempt))
        return results

    @staticmethod
    def _result_from_attempt(attempt: DictRow) -> PublishBatchAckItemResponse:
        """저장된 발행 시도를 Batch ACK 항목 결과로 변환한다."""
        if attempt["attempt_status"] == "published":
            result = PublishBatchResultStatus.PUBLISHED
        elif attempt["attempt_retryable"]:
            result = PublishBatchResultStatus.RETRY_SCHEDULED
        else:
            result = PublishBatchResultStatus.FAILED
        return PublishBatchAckItemResponse(
            content_id=attempt["content_id"],
            version=attempt["version"],
            result=result,
        )

    async def _acknowledge_batch_item(
        self,
        connection: AsyncConnection[DictRow],
        attempt: DictRow,
        item: PublishBatchAckItemRequest,
        acknowledged_at: datetime,
    ) -> PublishBatchAckItemResponse:
        """Claim된 Snapshot 한 건과 발행 시도를 같은 트랜잭션에서 갱신한다."""
        if item.status is PublishStatus.PUBLISHED:
            snapshot_status = "published"
            attempt_status = "published"
            retryable = False
            next_attempt_at = None
            result = PublishBatchResultStatus.PUBLISHED
        elif item.retryable and attempt["attempt_count"] < MAX_PUBLISH_ATTEMPTS:
            snapshot_status = "ready"
            attempt_status = "failed"
            retryable = True
            next_attempt_at = acknowledged_at + publish_retry_delay(
                attempt["attempt_count"]
            )
            result = PublishBatchResultStatus.RETRY_SCHEDULED
        else:
            snapshot_status = "failed"
            attempt_status = "failed"
            retryable = False
            next_attempt_at = None
            result = PublishBatchResultStatus.FAILED

        await connection.execute(
            """
            UPDATE agent.publish_snapshots
            SET
                status = %s,
                claim_id = NULL,
                claimed_by = NULL,
                lease_expires_at = NULL,
                next_attempt_at = %s,
                acknowledged_at = %s,
                failure_reason = %s
            WHERE id = %s
            """,
            (
                snapshot_status,
                next_attempt_at,
                acknowledged_at,
                item.failure_reason,
                attempt["snapshot_id"],
            ),
        )
        await connection.execute(
            """
            UPDATE agent.publish_attempts
            SET
                status = %s,
                retryable = %s,
                failure_reason = %s,
                acknowledged_at = %s
            WHERE id = %s
            """,
            (
                attempt_status,
                retryable,
                item.failure_reason,
                acknowledged_at,
                attempt["attempt_id"],
            ),
        )
        return PublishBatchAckItemResponse(
            content_id=item.content_id,
            version=item.version,
            result=result,
        )
