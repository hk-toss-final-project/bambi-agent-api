"""브리핑 준비 Job과 날짜별 Snapshot PostgreSQL 쿼리 계약을 검증한다."""

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from infrastructure.persistence.features.briefing_preparations import (
    enqueue_briefing_preparation_job,
    load_briefing_topic_snapshot,
    upsert_briefing_topic_snapshot,
)


class _Cursor:
    """준비된 Row 하나를 반환하는 Cursor 대역."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        """반환할 Row를 보관한다."""
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        """준비된 Row를 반환한다."""
        return self._row


class _Connection:
    """SQL과 바인딩 값을 기록하며 순서대로 Row를 반환하는 연결 대역."""

    def __init__(self, rows: list[dict[str, Any] | None]) -> None:
        """실행별 반환 Row와 기록 목록을 초기화한다."""
        self._rows = rows
        self.executed: list[tuple[str, Any]] = []

    async def execute(self, sql: str, params: Any = None) -> _Cursor:
        """SQL을 기록하고 다음 Cursor를 반환한다."""
        self.executed.append((sql, params))
        return _Cursor(self._rows.pop(0))


def _snapshot_row() -> dict[str, Any]:
    """Persistence 모델 변환에 사용할 Snapshot Row를 만든다."""
    return {
        "user_id": "user-1",
        "briefing_date": date(2026, 8, 12),
        "topics": ["반도체"],
        "reason": "저장 이력",
        "candidate_count": 10,
        "contexts_by_topic": {"반도체": [{"reference": "G1"}]},
        "prepared_by_job_id": "job-1",
        "updated_at": datetime(2026, 8, 11, tzinfo=UTC),
    }


def test_enqueue_briefing_preparation_job_returns_new_job_id() -> None:
    """새 사용자·날짜 조합은 준비 Job Payload와 함께 등록된다."""
    connection = _Connection([{"id": "job-1"}])

    job_id = asyncio.run(
        enqueue_briefing_preparation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            briefing_date=date(2026, 8, 12),
            idempotency_key="briefing:2026-08-12:user-1",
            limit=3,
            request_id="request-1",
        )
    )

    assert job_id == "job-1"
    assert "'briefing_preparation'" in connection.executed[0][0]
    assert connection.executed[0][1][2].obj == {
        "briefing_date": "2026-08-12",
        "limit": 3,
    }


def test_load_briefing_topic_snapshot_restores_topics_and_contexts() -> None:
    """저장된 JSON 근거와 주제 순서를 Snapshot 모델로 복원한다."""
    connection = _Connection([_snapshot_row()])

    snapshot = asyncio.run(
        load_briefing_topic_snapshot(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            briefing_date=date(2026, 8, 12),
        )
    )

    assert snapshot is not None
    assert snapshot.topics == ("반도체",)
    assert snapshot.contexts_by_topic["반도체"] == [{"reference": "G1"}]


def test_upsert_briefing_topic_snapshot_serializes_contexts() -> None:
    """준비 완료 시 Topic별 Context를 JSON 객체로 멱등 저장한다."""
    connection = _Connection([_snapshot_row()])

    snapshot = asyncio.run(
        upsert_briefing_topic_snapshot(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            briefing_date=date(2026, 8, 12),
            topics=["반도체"],
            reason="저장 이력",
            candidate_count=10,
            contexts_by_topic={"반도체": [{"reference": "G1"}]},
            prepared_by_job_id="job-1",
        )
    )

    assert snapshot.prepared_by_job_id == "job-1"
    assert connection.executed[0][1][5].obj == {
        "반도체": [{"reference": "G1"}]
    }
