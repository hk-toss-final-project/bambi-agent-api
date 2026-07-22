"""Report Builder Generation Job 등록의 예약 시각(scheduled_at) 영속화를 검증한다."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from infrastructure.persistence.features.generation_runtime import (
    enqueue_report_generation_job,
)


class _FakeCursor:
    """fetchone·fetchall을 지원하는 결정적 Cursor Test Double."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        """첫 번째 Row나 None을 반환한다."""
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        """전체 Row 목록을 반환한다."""
        return self._rows


class _FakeConnection:
    """SQL 실행 내역과 순서별 응답을 기록하는 Connection Test Double."""

    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        self._responses = responses
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    async def execute(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> _FakeCursor:
        """SQL을 기록하고 순서별 고정 Cursor를 반환한다."""
        self.executed.append((query, params))
        rows = self._responses.pop(0) if self._responses else []
        return _FakeCursor(rows)


def _connection_with_context() -> _FakeConnection:
    """Context 조회, Job·생성 요청 INSERT 순서의 응답을 준비한다."""
    return _FakeConnection(
        [
            [{"id": "context-1", "plan": "free", "preferred_language": "ko"}],
            [{"id": "job-1"}],
            [{"id": "request-1"}],
        ]
    )


def test_enqueue_persists_scheduled_at_for_reserved_generation() -> None:
    """예약 시각을 지정하면 Job INSERT에 scheduled_at 값이 전달된다."""
    connection = _connection_with_context()
    scheduled = datetime(2026, 7, 21, 7, 0, tzinfo=UTC)

    submission = asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="2026-07-21-user-1-interest_news_card",
            topic="개인 지식 그래프",
            content_type="interest_news_card",
            language="ko",
            scheduled_at=scheduled,
            request_id="request-1",
        )
    )

    assert submission.job_id == "job-1"
    assert submission.generation_request_id == "request-1"
    insert_sql, insert_params = connection.executed[1]
    assert "scheduled_at" in insert_sql
    assert "COALESCE(%s, clock_timestamp())" in insert_sql
    assert insert_params is not None and insert_params[-1] == scheduled


def test_enqueue_defaults_to_immediate_execution_without_schedule() -> None:
    """예약 시각을 생략하면 scheduled_at 파라미터가 NULL로 전달된다."""
    connection = _connection_with_context()

    asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-immediate",
            topic="개인 지식 그래프",
            content_type="interest_news_card",
            language=None,
            request_id="request-1",
        )
    )

    _, insert_params = connection.executed[1]
    assert insert_params is not None and insert_params[-1] is None
