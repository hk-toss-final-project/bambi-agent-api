"""SCH-009 Wiki Build 스케줄 조정 기능을 검증한다."""

import asyncio
from typing import Any

import pytest

from scheduler.features.wiki import sch_009


class _FakeCursor:
    """fetchall을 지원하는 결정적 Cursor Test Double."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        """조회 시 반환할 고정 Row 목록을 보관한다."""
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        """전체 Row 목록을 반환한다."""
        return self._rows


class _FakeConnection:
    """SQL 실행 내역과 순서별 응답을 기록하는 Connection Test Double."""

    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        """순서별 응답과 빈 SQL 실행 내역을 초기화한다."""
        self._responses = responses
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    async def execute(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> _FakeCursor:
        """SQL을 기록하고 순서별 고정 Cursor를 반환한다."""
        self.executed.append((query, params))
        rows = self._responses.pop(0) if self._responses else []
        return _FakeCursor(rows)


def test_sch_009_defers_pending_jobs_with_policy_minutes() -> None:
    """defer 동작이 조용 시간과 최대 대기시간으로 대기 Job을 미룬다."""
    connection = _FakeConnection([[{"id": "job-1"}, {"id": "job-2"}]])

    result = asyncio.run(
        sch_009(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            action="defer",
            quiet_minutes=10,
            max_wait_minutes=30,
        )
    )

    assert result.action == "defer"
    assert result.affected_jobs == 2
    assert connection.executed[0][1] == ("user-1", 30, 10)


def test_sch_009_releases_pending_jobs_for_forced_build() -> None:
    """release 동작이 강제 실행을 위해 대기 Job을 즉시 실행 가능으로 바꾼다."""
    connection = _FakeConnection([[{"id": "job-1"}]])

    result = asyncio.run(
        sch_009(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            action="release",
        )
    )

    assert result.action == "release"
    assert result.affected_jobs == 1
    assert "scheduled_at = clock_timestamp()" in connection.executed[0][0]


def test_sch_009_validates_required_inputs() -> None:
    """connection·user_id·action·대기시간 입력을 실행 전에 검증한다."""
    connection = _FakeConnection([])

    with pytest.raises(ValueError, match="connection"):
        asyncio.run(
            sch_009(
                None,  # type: ignore[arg-type]
                user_id="user-1",
            )
        )
    with pytest.raises(ValueError, match="user_id"):
        asyncio.run(
            sch_009(
                connection,  # type: ignore[arg-type]
                user_id="",
            )
        )
    with pytest.raises(ValueError, match="action"):
        asyncio.run(
            sch_009(
                connection,  # type: ignore[arg-type]
                user_id="user-1",
                action="rebuild",  # type: ignore[arg-type]
            )
        )
    with pytest.raises(ValueError, match="허용 범위"):
        asyncio.run(
            sch_009(
                connection,  # type: ignore[arg-type]
                user_id="user-1",
                quiet_minutes=-1,
                max_wait_minutes=30,
            )
        )
