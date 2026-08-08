"""Personal Wiki Worker의 PostgreSQL Job Claim·완료 기록을 검증한다."""

import asyncio
from typing import Any

import pytest

from infrastructure.persistence.features.jobs import (
    ClaimedAgentJob,
    EnqueuedCollectionRunJob,
    EnqueuedWikiBuildJob,
    claim_agent_job_by_id,
    claim_personal_wiki_jobs,
    claim_runnable_agent_jobs,
    complete_agent_job,
    defer_user_wiki_build_jobs,
    enqueue_global_collection_run_job,
    enqueue_personal_wiki_build_job,
    fail_agent_job,
    release_user_wiki_build_jobs,
)


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


def test_claim_runnable_agent_jobs_parameterizes_job_type() -> None:
    """일반화된 Batch Claim이 Job 유형을 SQL 파라미터로 받아 점유한다."""
    connection = _FakeConnection(
        [
            [
                {
                    "id": "job-9",
                    "user_id": "user-1",
                    "feature_id": "SVC-008",
                    "job_type": "report_generation",
                    "attempt_count": 1,
                    "max_attempts": 3,
                    "payload": {"topic": "개인화", "content_type": "article"},
                }
            ],
            [],
            [],
        ]
    )

    jobs = asyncio.run(
        claim_runnable_agent_jobs(
            connection,  # type: ignore[arg-type]
            job_type="report_generation",
            worker_id="worker-1",
            limit=5,
            lease_seconds=600,
        )
    )

    assert jobs[0].job_type == "report_generation"
    claim_sql, claim_params = connection.executed[0]
    assert "job_type = %s" in claim_sql
    assert "FOR UPDATE SKIP LOCKED" in claim_sql
    assert claim_params is not None and claim_params[0] == "report_generation"


def test_claim_agent_job_by_id_records_dev_lease_and_attempt() -> None:
    """개발 실행기가 지정 Job 하나를 Lease로 점유하고 Attempt를 남기는지 검증한다."""
    connection = _FakeConnection(
        [
            [
                {
                    "id": "job-1",
                    "user_id": "user-1",
                    "feature_id": "SVC-003",
                    "job_type": "personal_wiki_url",
                    "attempt_count": 1,
                    "max_attempts": 3,
                    "payload": {"url": "https://example.com"},
                }
            ],
            [],
            [],
        ]
    )

    claimed = asyncio.run(
        claim_agent_job_by_id(
            connection,  # type: ignore[arg-type]
            job_id="job-1",
            worker_id="dev-api:run-1",
            lease_seconds=180,
        )
    )

    assert claimed is not None
    assert claimed.job_type == "personal_wiki_url"
    assert connection.executed[0][1] == ("dev-api:run-1", 180, 5, "job-1")
    assert "agent.agent_job_attempts" in connection.executed[1][0]


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


def test_enqueue_global_collection_run_job_creates_system_job() -> None:
    """수동 실행 Job을 user_id 없이 queued로 등록하고 payload에 source_key를 담는다."""
    connection = _FakeConnection([[{"id": "job-1"}]])

    enqueued = asyncio.run(
        enqueue_global_collection_run_job(
            connection,  # type: ignore[arg-type]
            source_key="interest-taxonomy-google-news",
            request_id="req-1",
        )
    )

    assert enqueued == EnqueuedCollectionRunJob(job_id="job-1", created=True)
    insert_sql, insert_params = connection.executed[0]
    assert "'global_collection_run'" in insert_sql
    assert "'SCH-021'" in insert_sql
    # 사용자 소속이 없는 시스템 Job이라 user_id는 NULL로 저장한다.
    assert "NULL" in insert_sql
    assert "ON CONFLICT (feature_id, COALESCE(user_id, ''), idempotency_key)" in insert_sql
    assert insert_params is not None
    # 마지막 파라미터는 Request ID(추적·멱등 Key 재료)다.
    assert insert_params[-1] == "req-1"


def test_enqueue_global_collection_run_job_reuses_on_idempotency_conflict() -> None:
    """같은 source_key·request_id 재요청은 새 Job 없이 기존 Job을 반환한다."""
    connection = _FakeConnection([[], [{"id": "job-9"}]])

    enqueued = asyncio.run(
        enqueue_global_collection_run_job(
            connection,  # type: ignore[arg-type]
            source_key="latest-naver",
            request_id="req-9",
        )
    )

    assert enqueued == EnqueuedCollectionRunJob(job_id="job-9", created=False)
    assert "DO NOTHING" in connection.executed[0][0]
    assert "SELECT id" in connection.executed[1][0]


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


def test_defer_user_wiki_build_jobs_applies_quiet_window_with_max_wait_cap() -> None:
    """대기 Job 연기가 조용 시간과 첫 대기 기준 최대 대기 상한을 함께 사용한다."""
    connection = _FakeConnection([[{"id": "job-1"}, {"id": "job-2"}]])

    affected = asyncio.run(
        defer_user_wiki_build_jobs(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            quiet_minutes=10,
            max_wait_minutes=30,
        )
    )

    assert affected == 2
    sql, params = connection.executed[0]
    assert "job_type = 'personal_wiki_build'" in sql
    assert "status = 'queued'" in sql
    assert "attempt_count = 0" in sql
    assert "LEAST(" in sql
    assert "min(created_at)" in sql
    assert params == ("user-1", 30, 10)


def test_release_user_wiki_build_jobs_makes_queued_jobs_claimable_now() -> None:
    """강제 실행이 사용자의 queued Job scheduled_at을 현재 시각으로 당긴다."""
    connection = _FakeConnection([[{"id": "job-1"}, {"id": "job-2"}, {"id": "job-3"}]])

    affected = asyncio.run(
        release_user_wiki_build_jobs(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
        )
    )

    assert affected == 3
    sql, params = connection.executed[0]
    assert "scheduled_at = clock_timestamp()" in sql
    assert "status = 'queued'" in sql
    assert params == ("user-1",)


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
    claim_agent_job_by_id,
