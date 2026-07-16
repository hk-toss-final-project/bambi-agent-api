"""Personal Wiki Worker의 PostgreSQL Job Claim·완료 기록을 검증한다."""

import asyncio
from typing import Any

import pytest

from infrastructure.persistence.features.jobs import (
    ClaimedAgentJob,
    EnqueuedWikiBuildJob,
    claim_personal_wiki_jobs,
    complete_agent_job,
    enqueue_personal_wiki_build_job,
    fail_agent_job,
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


def test_claim_personal_wiki_jobs_uses_skip_locked_and_records_attempt() -> None:
    """Claim SQL이 SKIP LOCKED·Lease를 쓰고 Attempt와 Source 상태를 기록한다."""
    connection = _FakeConnection(
        [
            [
                {
                    "id": "job-1",
                    "user_id": "user-1",
                    "feature_id": "SVC-002",
                    "job_type": "personal_wiki_build",
                    "attempt_count": 1,
                    "max_attempts": 3,
                    "payload": {"source_document_version_id": "version-1"},
                }
            ],
            [],
            [],
        ]
    )

    jobs = asyncio.run(
        claim_personal_wiki_jobs(
            connection,  # type: ignore[arg-type]
            worker_id="worker-1",
            limit=5,
            lease_seconds=600,
        )
    )

    assert jobs == [
        ClaimedAgentJob(
            job_id="job-1",
            user_id="user-1",
            feature_id="SVC-002",
            job_type="personal_wiki_build",
            attempt_number=1,
            max_attempts=3,
            payload={"source_document_version_id": "version-1"},
        )
    ]
    claim_sql = connection.executed[0][0]
    assert "FOR UPDATE SKIP LOCKED" in claim_sql
    assert "lease_expires_at" in claim_sql
    assert "agent.agent_job_attempts" in connection.executed[1][0]
    assert "status = 'processing'" in connection.executed[2][0]


def test_claim_personal_wiki_jobs_validates_limits() -> None:
    """Batch 크기와 Lease 제약을 DB 호출 전에 검증한다."""
    connection = _FakeConnection([])

    with pytest.raises(ValueError, match="limit"):
        asyncio.run(
            claim_personal_wiki_jobs(
                connection,  # type: ignore[arg-type]
                worker_id="worker-1",
                limit=0,
                lease_seconds=600,
            )
        )


def test_complete_agent_job_updates_job_attempt_and_source_event() -> None:
    """Job 완료가 Job·Attempt·Source Event 세 상태를 함께 갱신한다."""
    connection = _FakeConnection([[{"id": "job-1"}], [], []])
    job = ClaimedAgentJob(
        job_id="job-1",
        user_id="user-1",
        feature_id="SVC-002",
        job_type="personal_wiki_build",
        attempt_number=1,
        max_attempts=3,
    )

    asyncio.run(
        complete_agent_job(
            connection,  # type: ignore[arg-type]
            job=job,
            worker_id="worker-1",
            result={"wiki_version_id": "wiki-1"},
        )
    )

    assert "status = 'completed'" in connection.executed[0][0]
    assert "lease_expires_at > clock_timestamp()" in connection.executed[0][0]
    assert "agent.agent_job_attempts" in connection.executed[1][0]
    assert "agent.wiki_source_events" in connection.executed[2][0]


def test_fail_agent_job_requires_active_lease_before_updating_attempt() -> None:
    """Job 실패도 유효한 Lease 소유자만 Attempt와 Source 상태를 바꾸도록 제한한다."""
    connection = _FakeConnection([[{"id": "job-1"}], [], []])
    job = ClaimedAgentJob(
        job_id="job-1",
        user_id="user-1",
        feature_id="SVC-002",
        job_type="personal_wiki_build",
        attempt_number=1,
        max_attempts=3,
    )

    status = asyncio.run(
        fail_agent_job(
            connection,  # type: ignore[arg-type]
            job=job,
            worker_id="worker-1",
            error_code="WIKI_BUILD_RETRYABLE",
            error_message="일시 오류",
            retryable=True,
        )
    )

    assert status == "queued"
    assert "status = 'running'" in connection.executed[0][0]
    assert "lease_expires_at > clock_timestamp()" in connection.executed[0][0]
    assert "RETURNING id" in connection.executed[0][0]


def test_enqueue_personal_wiki_build_job_creates_queued_job() -> None:
    """새 원본 Version 저장 시 Version 단위 멱등 키로 queued Job을 등록한다."""
    connection = _FakeConnection([[{"id": "job-1"}], []])

    enqueued = asyncio.run(
        enqueue_personal_wiki_build_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_id="doc-1",
            source_document_version_id="version-1",
            source_version=2,
            source_event_id="user-url-abc",
            source_event_row_id="event-1",
        )
    )

    assert enqueued == EnqueuedWikiBuildJob(job_id="job-1", created=True)
    insert_sql, insert_params = connection.executed[0]
    assert "'personal_wiki_build'" in insert_sql
    assert "ON CONFLICT (feature_id, COALESCE(user_id, ''), idempotency_key)" in insert_sql
    assert insert_params is not None
    assert insert_params[0] == "SVC-003"
    assert insert_params[2] == "user-url-abc:v2"
    event_sql, event_params = connection.executed[1]
    assert "agent.wiki_source_events" in event_sql
    assert event_params == ("job-1", "event-1")


def test_enqueue_personal_wiki_build_job_reuses_existing_job() -> None:
    """같은 이벤트·Version의 재요청은 새 Job 없이 기존 Job을 반환한다."""
    connection = _FakeConnection([[], [{"id": "job-9"}], []])

    enqueued = asyncio.run(
        enqueue_personal_wiki_build_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_id="doc-1",
            source_document_version_id="version-1",
            source_version=1,
            source_event_id="user-url-abc",
            source_event_row_id="event-1",
        )
    )

    assert enqueued == EnqueuedWikiBuildJob(job_id="job-9", created=False)
    assert "DO NOTHING" in connection.executed[0][0]
    assert "SELECT id" in connection.executed[1][0]
    assert connection.executed[2][1] == ("job-9", "event-1")


def test_enqueue_personal_wiki_build_job_skips_event_link_without_row_id() -> None:
    """이벤트 Row ID가 없으면 wiki_source_events 연결을 시도하지 않는다."""
    connection = _FakeConnection([[{"id": "job-1"}]])

    enqueued = asyncio.run(
        enqueue_personal_wiki_build_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_id="doc-1",
            source_document_version_id="version-1",
            source_version=1,
            source_event_id="user-url-abc",
        )
    )

    assert enqueued.created is True
    assert len(connection.executed) == 1


def test_fail_agent_job_stops_when_lease_is_lost() -> None:
    """Lease를 잃은 Worker는 Attempt와 Source Event까지 변경하지 않는다."""
    connection = _FakeConnection([[]])
    job = ClaimedAgentJob(
        job_id="job-1",
        user_id="user-1",
        feature_id="SVC-002",
        job_type="personal_wiki_build",
        attempt_number=1,
        max_attempts=3,
    )

    with pytest.raises(RuntimeError, match="Lease 소유권"):
        asyncio.run(
            fail_agent_job(
                connection,  # type: ignore[arg-type]
                job=job,
                worker_id="stale-worker",
                error_code="WIKI_BUILD_RETRYABLE",
                error_message="일시 오류",
                retryable=True,
            )
        )

    assert len(connection.executed) == 1
