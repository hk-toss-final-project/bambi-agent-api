"""SCH-009 Wiki Build 스케줄 조정 기능을 검증한다."""

import asyncio
from typing import Any

import pytest

from scheduler.features.wiki import sch_009
from shared.contracts import FeatureRequest


class _FakeCursor:
    """fetchall을 지원하는 결정적 Cursor Test Double."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

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


def test_sch_009_defers_pending_jobs_with_policy_minutes() -> None:
    """defer 동작이 조용 시간과 최대 대기시간으로 대기 Job을 미룬다."""
    connection = _FakeConnection([[{"id": "job-1"}, {"id": "job-2"}]])

    result = asyncio.run(
        sch_009(
            FeatureRequest(
                request_id="test-sch-009",
                user_id="user-1",
                payload={
                    "connection": connection,
                    "action": "defer",
                    "quiet_minutes": 10,
                    "max_wait_minutes": 30,
                },
            )
        )
    )

    assert result.feature_id == "SCH-009"
    assert result.data == {"action": "defer", "affected_jobs": 2}
    assert connection.executed[0][1] == ("user-1", 30, 10)


def test_sch_009_releases_pending_jobs_for_forced_build() -> None:
    """release 동작이 강제 실행을 위해 대기 Job을 즉시 실행 가능으로 바꾼다."""
    connection = _FakeConnection([[{"id": "job-1"}]])

    result = asyncio.run(
        sch_009(
            FeatureRequest(
                request_id="test-sch-009",
                user_id="user-1",
                payload={"connection": connection, "action": "release"},
            )
        )
    )

    assert result.data == {"action": "release", "affected_jobs": 1}
    assert "scheduled_at = clock_timestamp()" in connection.executed[0][0]


def test_sch_009_validates_required_inputs() -> None:
    """connection·user_id·action·대기시간 입력을 실행 전에 검증한다."""
    connection = _FakeConnection([])

    with pytest.raises(ValueError, match="connection"):
        asyncio.run(
            sch_009(
                FeatureRequest(
                    request_id="test-sch-009", user_id="user-1", payload={}
                )
            )
        )
    with pytest.raises(ValueError, match="user_id"):
        asyncio.run(
            sch_009(
                FeatureRequest(
                    request_id="test-sch-009",
                    user_id="",
                    payload={"connection": connection},
                )
            )
        )
    with pytest.raises(ValueError, match="action"):
        asyncio.run(
            sch_009(
                FeatureRequest(
                    request_id="test-sch-009",
                    user_id="user-1",
                    payload={"connection": connection, "action": "rebuild"},
                )
            )
        )
    with pytest.raises(ValueError, match="허용 범위"):
        asyncio.run(
            sch_009(
                FeatureRequest(
                    request_id="test-sch-009",
                    user_id="user-1",
                    payload={
                        "connection": connection,
                        "quiet_minutes": -1,
                        "max_wait_minutes": 30,
                    },
                )
            )
        )
