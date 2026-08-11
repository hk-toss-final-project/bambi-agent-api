"""Job 큐 Worker 공통 Batch 러너의 실행·실패 복원력을 검증한다."""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any

import pytest

from infrastructure.persistence.api import ClaimedAgentJob
from workers.features import batch_runner


class _FakeCursor:
    """fetchone·fetchall을 지원하는 결정적 Cursor Test Double."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        """순서대로 반환할 Row를 보관한다."""
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        """첫 번째 Row나 None을 반환한다."""
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        """전체 Row 목록을 반환한다."""
        return self._rows


class _FakeConnection:
    """transaction·close와 순서별 응답을 흉내 내는 Connection Test Double."""

    def __init__(self, responses: list[list[dict[str, Any]]] | None = None) -> None:
        """순서별 응답과 연결 상태를 초기화한다."""
        self._responses = list(responses or [])
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self.closed = False

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

    async def close(self) -> None:
        """연결 종료를 기록한다."""
        self.closed = True


def _job(job_id: str) -> ClaimedAgentJob:
    """러너가 처리할 Job 예시."""
    return ClaimedAgentJob(
        job_id=job_id,
        user_id="user-1",
        feature_id="SVC-008",
        job_type="report_generation",
        attempt_number=3,
        max_attempts=3,
        payload={},
    )


def test_record_job_failure_reports_lease_lost_instead_of_raising() -> None:
    """Lease를 잃어 실패 기록이 거부돼도 예외 대신 lease_lost 결과를 반환한다."""
    # set_system_job_scope, fail_agent_job의 첫 UPDATE가 Row를 못 찾는 상황.
    connection = _FakeConnection([[], []])

    result = asyncio.run(
        batch_runner.record_job_failure(
            connection,  # type: ignore[arg-type]
            job=_job("job-1"),
            worker_id="worker-1",
            error=TimeoutError("처리가 Lease보다 오래 걸림"),
            error_code_prefix="REPORT_GENERATION",
        )
    )

    assert result["status"] == "lease_lost"
    assert result["error_code"] == "REPORT_GENERATION_LEASE_LOST"
    assert result["job_id"] == "job-1"


def test_record_job_failure_returns_next_status_when_recorded() -> None:
    """실패 기록이 성공하면 접두사가 붙은 코드와 다음 상태를 반환한다."""
    # scope, UPDATE agent_jobs(RETURNING id), attempt UPDATE, event UPDATE 순서.
    connection = _FakeConnection([[], [{"id": "job-1"}], [], []])

    result = asyncio.run(
        batch_runner.record_job_failure(
            connection,  # type: ignore[arg-type]
            job=_job("job-1"),
            worker_id="worker-1",
            error=ValueError("Payload 누락"),
            error_code_prefix="WIKI_BUILD",
        )
    )

    assert result == {
        "job_id": "job-1",
        "status": "failed",
        "error_code": "WIKI_BUILD_INPUT_INVALID",
    }


def test_run_job_batch_processes_each_job_and_isolates_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch 러너가 Job별로 성공·실패를 격리해 결과를 누적한다."""
    connection = _FakeConnection()

    class _FakeAsyncConnectionPool:
        """모든 대여 요청에 고정 연결 대역을 반환하는 Pool 대체."""

        def __init__(self, **kwargs: Any) -> None:
            """Pool 생성 인자를 허용한다."""
            self.closed = False

        async def open(self, *, wait: bool = False) -> None:
            """실제 DB 연결 없이 Pool을 연다."""
            return None

        @asynccontextmanager
        async def connection(self) -> AsyncIterator[_FakeConnection]:
            """준비된 연결 대역을 빌려준다."""
            yield connection

        async def close(self) -> None:
            """Pool과 연결이 닫혔음을 기록한다."""
            self.closed = True
            await connection.close()

    claimed = [_job("job-1"), _job("job-2")]

    async def fake_scope(conn: Any) -> None:
        """테스트에서 DB 시스템 Scope 설정을 생략한다."""
        return None

    async def fake_claim(conn: Any, **kwargs: Any) -> list[ClaimedAgentJob]:
        """Claim 인자를 검증하고 준비된 Job 목록을 반환한다."""
        assert kwargs["job_type"] == "report_generation"
        assert kwargs["worker_id"] == "worker-1"
        return claimed

    async def fake_fail(conn: Any, **kwargs: Any) -> str:
        """Job 실패 후 재시도 대기 상태를 반환한다."""
        return "queued"

    async def process(conn: Any, job: ClaimedAgentJob) -> dict[str, object]:
        """job-2만 실패시키는 처리 함수."""
        if job.job_id == "job-2":
            raise RuntimeError("일시적 실패")
        return {"content_id": "content-1"}

    monkeypatch.setattr(
        batch_runner, "AsyncConnectionPool", _FakeAsyncConnectionPool
    )
    monkeypatch.setattr(batch_runner, "set_system_job_scope", fake_scope)
    monkeypatch.setattr(batch_runner, "wc_002", fake_claim)
    monkeypatch.setattr(batch_runner, "wc_006", fake_fail)

    results = asyncio.run(
        batch_runner.run_job_batch(
            database_url="postgresql://test",
            job_type="report_generation",
            worker_id="worker-1",
            limit=5,
            lease_seconds=600,
            error_code_prefix="REPORT_GENERATION",
            process=process,
        )
    )

    assert results[0] == {
        "job_id": "job-1",
        "status": "completed",
        "content_id": "content-1",
    }
    assert results[1]["status"] == "queued"
    assert results[1]["error_code"] == "REPORT_GENERATION_RETRYABLE"
    assert connection.closed is True
