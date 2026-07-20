"""Bambi Generation Worker의 실패 기록 복원력과 입력 검증을 검증한다."""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any

import pytest

from infrastructure.persistence.api import ClaimedAgentJob
from shared.contracts import FeatureRequest
from workers.features.bambi_generation import _record_job_failure, worker_003


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
    """transaction과 순서별 응답을 흉내 내는 Connection Test Double."""

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

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """psycopg transaction 문맥을 흉내 낸다."""
        yield


def _job() -> ClaimedAgentJob:
    """실패 기록 대상 Bambi Job 예시."""
    return ClaimedAgentJob(
        job_id="job-1",
        user_id="user-1",
        feature_id="SVC-008",
        job_type="bambi_generation",
        attempt_number=3,
        max_attempts=3,
        payload={"topic": "개인 지식 그래프", "content_type": "article"},
    )


def test_record_job_failure_reports_lease_lost_instead_of_raising() -> None:
    """Lease를 잃어 실패 기록이 거부돼도 예외 대신 lease_lost 결과를 반환한다."""
    # set_system_job_scope, fail_agent_job의 첫 UPDATE가 Row를 못 찾는 상황.
    connection = _FakeConnection([[], []])

    result = asyncio.run(
        _record_job_failure(
            connection,  # type: ignore[arg-type]
            job=_job(),
            worker_id="worker-1",
            error=TimeoutError("생성이 Lease보다 오래 걸림"),
        )
    )

    assert result["status"] == "lease_lost"
    assert result["error_code"] == "BAMBI_GENERATION_LEASE_LOST"
    assert result["job_id"] == "job-1"


def test_record_job_failure_returns_next_status_when_recorded() -> None:
    """실패 기록이 성공하면 fail_agent_job의 다음 상태를 그대로 반환한다."""
    # scope, UPDATE agent_jobs(RETURNING id), attempt UPDATE, event UPDATE 순서.
    connection = _FakeConnection([[], [{"id": "job-1"}], [], []])

    result = asyncio.run(
        _record_job_failure(
            connection,  # type: ignore[arg-type]
            job=_job(),
            worker_id="worker-1",
            error=ValueError("Payload에 topic 없음"),
        )
    )

    assert result == {
        "job_id": "job-1",
        "status": "failed",
        "error_code": "BAMBI_GENERATION_INPUT_INVALID",
    }


def test_worker_003_requires_database_url() -> None:
    """WORKER-003이 DB 연결 없이 호출되면 명확한 검증 오류를 낸다."""
    request = FeatureRequest(
        request_id="request-1",
        actor_id="bambi-worker",
        payload={"worker_id": "worker-1"},
    )

    with pytest.raises(ValueError, match="database_url"):
        asyncio.run(worker_003(request))
