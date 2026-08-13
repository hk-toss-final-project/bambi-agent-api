"""Job 큐 Worker 공통 Batch 러너의 실행·실패 복원력을 검증한다."""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent.llm.features.client import record_llm_call_observation
from infrastructure.persistence.api import ClaimedAgentJob, ProviderRateLimitDecision
from workers.features import batch_runner
from workers.runtime.api import JobInputError, ProviderRateLimitPolicy


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


def _job(
    job_id: str,
    *,
    attempt_number: int = 3,
    max_attempts: int = 3,
) -> ClaimedAgentJob:
    """러너가 처리할 Job 예시."""
    return ClaimedAgentJob(
        job_id=job_id,
        user_id="user-1",
        feature_id="SVC-008",
        job_type="report_generation",
        attempt_number=attempt_number,
        max_attempts=max_attempts,
        payload={},
    )


def _rate_policy() -> ProviderRateLimitPolicy:
    """Batch 러너 테스트용 OpenAI 예약 정책을 만든다."""
    return ProviderRateLimitPolicy(
        provider="openai",
        resource_key="gpt-4.1-mini",
        estimated_requests=2,
        estimated_tokens=10_000,
        default_rpm=60,
        default_tpm=60_000,
        max_wait_slice_seconds=5,
    )


def test_wait_for_provider_capacity_releases_connection_before_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RPM·TPM 대기는 Pool 연결을 반환한 뒤 수행해 연결 고갈을 막는다."""
    active_connections = 0
    sleeps: list[float] = []
    decisions = [
        ProviderRateLimitDecision(
            allowed=False,
            retry_at=datetime.now(UTC) + timedelta(seconds=10),
            remaining_requests=0,
            remaining_tokens=0,
        ),
        ProviderRateLimitDecision(
            allowed=True,
            retry_at=None,
            remaining_requests=10,
            remaining_tokens=10_000,
        ),
    ]

    class _Pool:
        """활성 대여 수를 기록하는 Pool 대역."""

        @asynccontextmanager
        async def connection(self) -> AsyncIterator[_FakeConnection]:
            """연결 대여 구간의 활성 수를 증감한다."""
            nonlocal active_connections
            active_connections += 1
            try:
                yield _FakeConnection()
            finally:
                active_connections -= 1

    async def fake_reserve(connection: Any, **kwargs: Any) -> Any:
        """대기 후 허용 결정을 순서대로 반환한다."""
        return decisions.pop(0)

    async def fake_sleep(delay: float) -> None:
        """Sleep 시점에 DB 연결이 반환됐는지 검증한다."""
        assert active_connections == 0
        sleeps.append(delay)

    monkeypatch.setattr(batch_runner, "wc_014", fake_reserve)
    monkeypatch.setattr(batch_runner.asyncio, "sleep", fake_sleep)

    asyncio.run(
        batch_runner.wait_for_provider_capacity(  # type: ignore[arg-type]
            _Pool(),
            policy=_rate_policy(),
        )
    )

    assert sleeps == [5]
    assert active_connections == 0


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
            job=_job("job-1", attempt_number=1),
            worker_id="worker-1",
            error=JobInputError("Payload 누락"),
            error_code_prefix="WIKI_BUILD",
        )
    )

    assert result == {
        "job_id": "job-1",
        "status": "failed",
        "error_code": "WIKI_BUILD_INPUT_INVALID",
    }


def test_record_job_failure_retries_runtime_value_error() -> None:
    """모델 출력 파싱 같은 일반 ValueError는 입력 오류로 오분류하지 않는다."""
    connection = _FakeConnection([[], [{"id": "job-1"}], [], []])

    result = asyncio.run(
        batch_runner.record_job_failure(
            connection,  # type: ignore[arg-type]
            job=_job("job-1", attempt_number=1),
            worker_id="worker-1",
            error=ValueError("LLM 응답 JSON을 파싱하지 못했습니다."),
            error_code_prefix="REPORT_GENERATION",
        )
    )

    assert result["status"] == "queued"
    assert result["error_code"] == "REPORT_GENERATION_RETRYABLE"


def test_maintain_job_lease_renews_until_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """공통 heartbeat가 별도 연결에서 Lease를 연장하고 종료 신호에 멈춘다."""
    connection = _FakeConnection()
    stop_event = asyncio.Event()
    calls: list[dict[str, Any]] = []

    class _Pool:
        """heartbeat용 고정 연결을 빌려주는 Pool 대역."""

        @asynccontextmanager
        async def connection(self) -> AsyncIterator[_FakeConnection]:
            """준비된 연결을 heartbeat에 제공한다."""
            yield connection

    async def fake_scope(conn: Any) -> None:
        """테스트에서는 시스템 Scope SQL을 생략한다."""

    async def fake_heartbeat(conn: Any, **kwargs: Any) -> datetime:
        """첫 Lease 갱신을 기록하고 루프 종료를 요청한다."""
        calls.append(kwargs)
        stop_event.set()
        return datetime.now(UTC)

    monkeypatch.setattr(batch_runner, "set_system_job_scope", fake_scope)
    monkeypatch.setattr(batch_runner, "wc_003", fake_heartbeat)

    asyncio.run(
        batch_runner.maintain_job_lease(
            _Pool(),  # type: ignore[arg-type]
            job=_job("job-1"),
            worker_id="worker-1",
            lease_seconds=600,
            stop_event=stop_event,
            interval_seconds=0.001,
        )
    )

    assert len(calls) == 1
    assert calls[0]["worker_id"] == "worker-1"
    assert calls[0]["lease_seconds"] == 600


def test_heartbeat_ownership_failure_cancels_running_operation() -> None:
    """Lease 소유권을 잃으면 오래 도는 Job 실행을 취소해 중복 처리를 막는다."""
    async def scenario() -> None:
        """실행 시작 뒤 heartbeat를 실패시키고 취소 정리를 확인한다."""
        started = asyncio.Event()
        cancelled = asyncio.Event()
        stop_event = asyncio.Event()

        async def fail_heartbeat() -> None:
            """Job 실행이 시작되면 Lease 소유권 상실을 보고한다."""
            await started.wait()
            raise RuntimeError("Job Lease 소유권이 없습니다: job-1")

        async def operation() -> dict[str, object]:
            """heartbeat 실패 전까지 계속 실행 중인 Job을 흉내 낸다."""
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            return {}

        heartbeat_task = asyncio.create_task(fail_heartbeat())
        with pytest.raises(RuntimeError, match="Lease 소유권"):
            await batch_runner._run_with_job_heartbeat(  # noqa: SLF001
                operation=operation,
                heartbeat_task=heartbeat_task,
                stop_event=stop_event,
            )
        assert cancelled.is_set()
        assert stop_event.is_set()

    asyncio.run(scenario())


def test_job_serialization_lock_uses_stable_postgres_advisory_key() -> None:
    """직렬화 Lock과 Unlock은 같은 문자열 Hash를 사용한다."""
    connection = _FakeConnection([[{"unlocked": True}]])

    async def run() -> None:
        """같은 키로 Lock을 획득하고 해제한다."""
        await batch_runner._lock_job_serialization_key(  # noqa: SLF001
            connection,  # type: ignore[arg-type]
            key="personal_wiki_build:user-1",
        )
        await batch_runner._unlock_job_serialization_key(  # noqa: SLF001
            connection,  # type: ignore[arg-type]
            key="personal_wiki_build:user-1",
        )

    asyncio.run(run())

    assert len(connection.executed) == 2
    assert "pg_advisory_lock" in connection.executed[0][0]
    assert "pg_advisory_unlock" in connection.executed[1][0]
    assert connection.executed[0][1] == connection.executed[1][1]


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

    claim_queue = [_job("job-1"), _job("job-2")]

    async def fake_scope(conn: Any) -> None:
        """테스트에서 DB 시스템 Scope 설정을 생략한다."""
        return None

    async def fake_claim(conn: Any, **kwargs: Any) -> list[ClaimedAgentJob]:
        """Claim 인자를 검증하고 준비된 Job 목록을 반환한다."""
        assert kwargs["job_type"] == "report_generation"
        assert kwargs["worker_id"] == "worker-1"
        assert kwargs["limit"] == 1
        return [claim_queue.pop(0)] if claim_queue else []

    async def fake_fail(conn: Any, **kwargs: Any) -> str:
        """일반 실행 오류가 재시도 불가로 전달됐는지 검증한다."""
        assert kwargs["retryable"] is False
        return "failed"

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
    assert results[1]["status"] == "failed"
    assert results[1]["error_code"] == "REPORT_GENERATION_EXECUTION_FAILED"
    assert connection.closed is True


def test_run_job_batch_flushes_usage_for_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """성공·실패 Job 모두에서 수집한 Provider 호출을 업무 Context와 저장한다."""
    connection = _FakeConnection()

    class _FakeAsyncConnectionPool:
        """모든 대여 요청에 고정 연결을 반환하는 Pool 대역."""

        def __init__(self, **kwargs: Any) -> None:
            """Pool 생성 인자를 허용한다."""

        async def open(self, *, wait: bool = False) -> None:
            """실제 DB 연결 없이 Pool을 연다."""

        @asynccontextmanager
        async def connection(self) -> AsyncIterator[_FakeConnection]:
            """준비된 연결 대역을 빌려준다."""
            yield connection

        async def close(self) -> None:
            """테스트 Pool을 닫는다."""

    jobs = [
        ClaimedAgentJob(
            job_id="job-morning",
            user_id="user-1",
            feature_id="SVC-008",
            job_type="report_generation",
            attempt_number=1,
            max_attempts=3,
            request_id="request-1",
            trace_id="trace-1",
            payload={"generation_scope": "WIKI_BRIEFING"},
        ),
        ClaimedAgentJob(
            job_id="job-wiki",
            user_id="user-2",
            feature_id="WBA-002",
            job_type="personal_wiki_build",
            attempt_number=2,
            max_attempts=3,
            payload={"trigger": "maintenance", "mode": "full_rebuild"},
        ),
    ]
    flushed: list[tuple[str, list[str]]] = []

    async def fake_scope(conn: Any) -> None:
        """테스트에서 DB 시스템 Scope 설정을 생략한다."""

    async def fake_claim(conn: Any, **kwargs: Any) -> list[ClaimedAgentJob]:
        """준비한 Job을 한 건씩 반환한다."""
        return [jobs.pop(0)] if jobs else []

    async def fake_fail(conn: Any, **kwargs: Any) -> str:
        """실패 Job을 최종 실패로 반환한다."""
        return "failed"

    async def fake_flush(pool: Any, *, context: Any, observations: Any) -> int:
        """저장 대상 업무 분류와 관찰 상태를 기록한다."""
        flushed.append((context.workload_type, [item.status for item in observations]))
        return len(observations)

    class _Response:
        """사용량과 요청 ID가 있는 최소 Provider 응답."""

        usage_metadata = {"input_tokens": 10, "output_tokens": 2}
        response_metadata = {"headers": {"x-request-id": "provider-1"}}

    async def process(conn: Any, job: ClaimedAgentJob) -> dict[str, object]:
        """호출 관찰을 하나 만든 뒤 Wiki 유지 Job만 실패시킨다."""
        record_llm_call_observation(
            model="gpt-4.1-mini",
            input_tokens=10,
            output_tokens=2,
            value=_Response(),
        )
        if job.job_id == "job-wiki":
            raise RuntimeError("유지 실패")
        return {}

    monkeypatch.setattr(batch_runner, "AsyncConnectionPool", _FakeAsyncConnectionPool)
    monkeypatch.setattr(batch_runner, "set_system_job_scope", fake_scope)
    monkeypatch.setattr(batch_runner, "wc_002", fake_claim)
    monkeypatch.setattr(batch_runner, "wc_006", fake_fail)
    monkeypatch.setattr(batch_runner, "flush_job_llm_usage_logs", fake_flush)

    results = asyncio.run(
        batch_runner.run_job_batch(
            database_url="postgresql://test",
            job_type="report_generation",
            worker_id="worker-1",
            limit=2,
            lease_seconds=600,
            error_code_prefix="TEST",
            process=process,
        )
    )

    assert [item[0] for item in flushed] == ["report_morning", "wiki_maintenance"]
    assert [item[1] for item in flushed] == [["succeeded"], ["succeeded"]]
    assert [result["status"] for result in results] == ["completed", "failed"]


def test_run_job_batch_claims_only_when_an_execution_slot_is_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실행 중인 슬롯 수를 넘겨 Job을 미리 점유하지 않고 완료 직후 보충한다."""
    connection = _FakeConnection()
    claim_queue = [_job("job-1"), _job("job-2"), _job("job-3")]
    claimed_ids: list[str] = []
    started_ids: list[str] = []
    two_started = asyncio.Event()
    release = asyncio.Event()

    class _FakeAsyncConnectionPool:
        """동적 Claim 순서 검증에 쓰는 연결 Pool 대역."""

        def __init__(self, **kwargs: Any) -> None:
            """실제 Pool 생성 인자를 허용한다."""

        async def open(self, *, wait: bool = False) -> None:
            """실제 DB 연결 없이 Pool을 연다."""

        @asynccontextmanager
        async def connection(self) -> AsyncIterator[_FakeConnection]:
            """고정 연결 대역을 빌려준다."""
            yield connection

        async def close(self) -> None:
            """테스트 Pool을 닫는다."""

    async def fake_scope(conn: Any) -> None:
        """테스트에서는 시스템 Scope SQL을 생략한다."""

    async def fake_claim(conn: Any, **kwargs: Any) -> list[ClaimedAgentJob]:
        """호출마다 Job 하나만 점유하고 점유 순서를 기록한다."""
        assert kwargs["limit"] == 1
        if not claim_queue:
            return []
        job = claim_queue.pop(0)
        claimed_ids.append(job.job_id)
        return [job]

    async def process(conn: Any, job: ClaimedAgentJob) -> dict[str, object]:
        """처음 두 슬롯을 막아 세 번째 Job의 선점 여부를 관찰한다."""
        started_ids.append(job.job_id)
        if len(started_ids) == 2:
            two_started.set()
        await release.wait()
        return {}

    monkeypatch.setattr(
        batch_runner, "AsyncConnectionPool", _FakeAsyncConnectionPool
    )
    monkeypatch.setattr(batch_runner, "set_system_job_scope", fake_scope)
    monkeypatch.setattr(batch_runner, "wc_002", fake_claim)

    async def scenario() -> list[dict[str, object]]:
        """두 슬롯이 찬 동안 점유 수를 확인한 뒤 실행을 끝낸다."""
        task = asyncio.create_task(
            batch_runner.run_job_batch(
                database_url="postgresql://test",
                job_type="report_generation",
                worker_id="worker-1",
                limit=3,
                concurrency=2,
                lease_seconds=600,
                error_code_prefix="REPORT_GENERATION",
                process=process,
            )
        )
        await asyncio.wait_for(two_started.wait(), timeout=1)
        await asyncio.sleep(0)
        assert claimed_ids == ["job-1", "job-2"]
        release.set()
        return await task

    results = asyncio.run(scenario())

    assert claimed_ids == ["job-1", "job-2", "job-3"]
    assert [result["job_id"] for result in results] == claimed_ids
