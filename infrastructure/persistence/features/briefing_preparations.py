"""아침 브리핑 준비 Job과 날짜별 근거 Snapshot을 PostgreSQL에 저장한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

type DictRow = dict[str, Any]


@dataclass(frozen=True, slots=True)
class StoredBriefingTopicSnapshot:
    """사용자·날짜별로 확정된 브리핑 주제와 사전 수집 근거."""

    user_id: str
    briefing_date: date
    topics: tuple[str, ...]
    reason: str
    candidate_count: int
    contexts_by_topic: dict[str, list[dict[str, object]]]
    prepared_by_job_id: str
    prepared_at: datetime


def _snapshot_from_row(row: Mapping[str, Any]) -> StoredBriefingTopicSnapshot:
    """PostgreSQL Row를 불변 브리핑 Snapshot 모델로 변환한다."""
    raw_contexts = row.get("contexts_by_topic") or {}
    contexts = {
        str(topic): [dict(item) for item in items if isinstance(item, Mapping)]
        for topic, items in raw_contexts.items()
        if isinstance(items, Sequence) and not isinstance(items, (str, bytes))
    }
    return StoredBriefingTopicSnapshot(
        user_id=str(row["user_id"]),
        briefing_date=row["briefing_date"],
        topics=tuple(str(topic) for topic in (row.get("topics") or ())),
        reason=str(row.get("reason") or ""),
        candidate_count=int(row.get("candidate_count") or 0),
        contexts_by_topic=contexts,
        prepared_by_job_id=str(row["prepared_by_job_id"]),
        prepared_at=row["updated_at"],
    )


async def enqueue_briefing_preparation_job(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    briefing_date: date,
    idempotency_key: str,
    limit: int,
    request_id: str,
) -> str:
    """사용자·날짜별 브리핑 준비 Job을 멱등 등록하고 Job ID를 반환한다."""
    cursor = await connection.execute(
        """
        INSERT INTO agent.agent_jobs (
            feature_id,
            job_type,
            user_id,
            idempotency_key,
            status,
            progress,
            priority,
            payload,
            retryable,
            request_id
        ) VALUES (
            'REPORT-022', 'briefing_preparation', %s, %s, 'queued', 0, 200,
            %s, true, %s
        )
        ON CONFLICT (feature_id, COALESCE(user_id, ''), idempotency_key)
        DO NOTHING
        RETURNING id
        """,
        (
            user_id,
            idempotency_key,
            Jsonb(
                {
                    "briefing_date": briefing_date.isoformat(),
                    "limit": limit,
                }
            ),
            request_id,
        ),
    )
    row = await cursor.fetchone()
    if row is not None:
        return str(row["id"])
    existing_cursor = await connection.execute(
        """
        SELECT id
        FROM agent.agent_jobs
        WHERE feature_id = 'REPORT-022'
          AND COALESCE(user_id, '') = %s
          AND idempotency_key = %s
        """,
        (user_id, idempotency_key),
    )
    existing = await existing_cursor.fetchone()
    if existing is None:
        raise RuntimeError(
            f"멱등 충돌한 브리핑 준비 Job을 찾을 수 없습니다: {idempotency_key}"
        )
    return str(existing["id"])


async def load_briefing_topic_snapshot(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    briefing_date: date,
) -> StoredBriefingTopicSnapshot | None:
    """사용자와 날짜가 일치하는 브리핑 준비 Snapshot을 조회한다."""
    cursor = await connection.execute(
        """
        SELECT
            user_id,
            briefing_date,
            topics,
            reason,
            candidate_count,
            contexts_by_topic,
            prepared_by_job_id,
            updated_at
        FROM agent.briefing_topic_snapshots
        WHERE user_id = %s
          AND briefing_date = %s
        """,
        (user_id, briefing_date),
    )
    row = await cursor.fetchone()
    return _snapshot_from_row(row) if row is not None else None


async def upsert_briefing_topic_snapshot(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    briefing_date: date,
    topics: Sequence[str],
    reason: str,
    candidate_count: int,
    contexts_by_topic: Mapping[str, Sequence[Mapping[str, object]]],
    prepared_by_job_id: str,
) -> StoredBriefingTopicSnapshot:
    """준비 결과를 사용자·날짜 기준으로 멱등 저장하고 확정 Snapshot을 반환한다."""
    serialized_contexts = {
        str(topic): [dict(context) for context in contexts]
        for topic, contexts in contexts_by_topic.items()
    }
    cursor = await connection.execute(
        """
        INSERT INTO agent.briefing_topic_snapshots (
            user_id,
            briefing_date,
            topics,
            reason,
            candidate_count,
            contexts_by_topic,
            prepared_by_job_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, briefing_date)
        DO UPDATE SET
            topics = EXCLUDED.topics,
            reason = EXCLUDED.reason,
            candidate_count = EXCLUDED.candidate_count,
            contexts_by_topic = EXCLUDED.contexts_by_topic,
            prepared_by_job_id = EXCLUDED.prepared_by_job_id
        RETURNING
            user_id,
            briefing_date,
            topics,
            reason,
            candidate_count,
            contexts_by_topic,
            prepared_by_job_id,
            updated_at
        """,
        (
            user_id,
            briefing_date,
            list(topics),
            reason,
            candidate_count,
            Jsonb(serialized_contexts),
            prepared_by_job_id,
        ),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("브리핑 준비 Snapshot 저장 결과가 없습니다.")
    return _snapshot_from_row(row)
