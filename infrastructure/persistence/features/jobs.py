"""Agent Job Claim·완료·실패 영속화.

Personal Wiki Worker가 PostgreSQL Job을 Lease로 점유하고, 각 시도의
결과와 최종 Job 상태를 멱등적으로 기록하는 DB-026 구현이다.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from domain.jobs.api import AgentJobLeaseSnapshot, job_001, job_006, job_009, job_010
from domain.personal_wiki.source_events.api import wse_013

# JOB-009 회수가 남기는 실패 사유. Worker 쪽 실패(fail_agent_job)와 구분해
# "누가 실패시켰는지"를 감사 추적에서 바로 알 수 있게 한다.
LEASE_TIMEOUT_ERROR_CODE = "lease_timeout_attempts_exhausted"
LEASE_TIMEOUT_ERROR_MESSAGE = (
    "Lease가 만료됐지만 시도를 다 써서 아무도 다시 집지 못한 채 running으로 "
    "남아 있었습니다. Scheduler가 JOB-009로 회수해 failed로 마감했습니다."
)
STALE_ATTEMPT_ERROR_CODE = "lease_expired"
STALE_ATTEMPT_ERROR_MESSAGE = (
    "Worker Lease가 만료되어 새 Attempt가 Job을 다시 점유했습니다."
)

type DictRow = dict[str, Any]

_MAINTENANCE_PIPELINE_VERSIONS = frozenset(
    {"legacy_v1", "langgraph_v2", "langgraph_v3"}
)


@dataclass(frozen=True, slots=True)
class CompletedAgentJobAnchor:
    """Queue를 거치지 않고 즉시 완료 처리된 Agent Job의 식별자."""

    job_id: str


async def create_completed_agent_job(
    connection: AsyncConnection[DictRow],
    *,
    feature_id: str,
    job_type: str,
    user_id: str,
    payload: Mapping[str, object],
    request_id: str | None,
) -> CompletedAgentJobAnchor:
    """이미 동기로 끝난 처리가 FK(built_by_job_id 등)를 남기도록 Job Row를 만든다.

    `status`를 처음부터 `completed`로 저장하므로 Queue 조회(`status = 'queued'`)는
    이 Row를 절대 집어가지 않는다. MCP Write처럼 Worker Queue를 거치지 않고
    바로 처리를 끝낸 경로에서만 사용한다.
    """
    creation = await job_001(
        feature_id=feature_id,
        job_type=job_type,
        user_id=user_id,
        idempotency_parts=[job_type, str(uuid4())],
        payload=dict(payload),
        request_id=request_id,
    )
    cursor = await connection.execute(
        """
        INSERT INTO agent.agent_jobs (
            feature_id,
            job_type,
            user_id,
            idempotency_key,
            status,
            progress,
            payload,
            retryable,
            request_id,
            completed_at
        ) VALUES (%s, %s, %s, %s, 'completed', 100, %s, false, %s, clock_timestamp())
        RETURNING id
        """,
        (
            creation.feature_id,
            creation.job_type,
            creation.user_id,
            creation.idempotency_key,
            Jsonb(creation.payload),
            creation.request_id,
        ),
    )
    row = await cursor.fetchone()
    return CompletedAgentJobAnchor(job_id=str(row["id"]))


@dataclass(frozen=True, slots=True)
class ClaimedAgentJob:
    """Worker가 Lease로 점유한 Agent Job 하나."""

    job_id: str
    user_id: str
    feature_id: str
    job_type: str
    attempt_number: int
    max_attempts: int
    request_id: str | None = None
    trace_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StoredAgentJob:
    """API와 개발 실행기가 조회하는 Agent Job 저장 레코드."""

    job_id: str
    user_id: str
    feature_id: str
    job_type: str
    idempotency_key: str
    status: str
    progress: int
    request_id: str
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ClaimAgentJobsCommand:
    """DB-026 Batch Job Claim 입력."""

    job_type: str
    worker_id: str
    limit: int
    lease_seconds: int


@dataclass(frozen=True, slots=True)
class CompleteAgentJobCommand:
    """DB-026 Agent Job 완료 입력."""

    job: ClaimedAgentJob
    worker_id: str
    result: dict[str, object]


@dataclass(frozen=True, slots=True)
class FailAgentJobCommand:
    """DB-026 Agent Job 실패와 재시도 입력."""

    job: ClaimedAgentJob
    worker_id: str
    error_code: str
    error_message: str
    retryable: bool
    retry_delay_seconds: float | None = None


type AgentJobStorageCommand = (
    ClaimAgentJobsCommand | CompleteAgentJobCommand | FailAgentJobCommand
)


async def set_system_job_scope(connection: AsyncConnection[DictRow]) -> None:
    """Job Worker Transaction에 RLS 시스템 Scope를 설정한다."""
    await connection.execute("SET LOCAL app.access_scope = 'system'")


async def _record_claimed_attempt(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
) -> None:
    """이전 running Attempt를 timed_out으로 닫고 새 Claim Attempt를 기록한다.

    Job 재점유와 같은 Transaction에서 실행되므로, Lease가 만료된 이전 Worker의
    Attempt가 running으로 남은 채 새 Attempt가 추가되는 좀비 상태를 막는다.
    """
    await connection.execute(
        """
        WITH timed_out AS (
            UPDATE agent.agent_job_attempts
            SET
                status = 'timed_out',
                error_code = %s,
                error_message = %s,
                completed_at = clock_timestamp()
            WHERE job_id = %s
              AND status = 'running'
              AND attempt_number < %s
        )
        INSERT INTO agent.agent_job_attempts (
            job_id,
            user_id,
            attempt_number,
            worker_id,
            status
        ) VALUES (%s, %s, %s, %s, 'running')
        ON CONFLICT (job_id, attempt_number) DO NOTHING
        """,
        (
            STALE_ATTEMPT_ERROR_CODE,
            STALE_ATTEMPT_ERROR_MESSAGE,
            job.job_id,
            job.attempt_number,
            job.job_id,
            job.user_id,
            job.attempt_number,
            worker_id,
        ),
    )


async def claim_runnable_agent_jobs(
    connection: AsyncConnection[DictRow],
    *,
    job_type: str,
    worker_id: str,
    limit: int,
    lease_seconds: int,
) -> list[ClaimedAgentJob]:
    """지정한 유형의 실행 가능한 Job을 SKIP LOCKED와 Lease로 Batch 점유한다.

    queued이거나 Lease가 만료된 running Job 중 scheduled_at이 지난 것을
    우선순위 순서로 점유하고 Job별 Attempt를 기록한다. Wiki 원본이 연결된
    Job이면 wiki_source_events 상태도 processing으로 동기화한다.

    Args:
        connection: 시스템 Scope가 설정된 DB 연결
        job_type: 점유할 Job 유형 (예: personal_wiki_build, report_generation)
        worker_id: Job Lease 소유자 식별자
        limit: 한 번에 점유할 최대 Job 수
        lease_seconds: Job Lease 유지 시간(초)

    Returns:
        점유한 Job 목록
    """
    if not 1 <= limit <= 100:
        raise ValueError("Job Claim limit은 1에서 100 사이여야 합니다.")
    if not 30 <= lease_seconds <= 3600:
        raise ValueError("Job Lease는 30초에서 3600초 사이여야 합니다.")
    claimed_progress = await job_006(0, 5)
    cursor = await connection.execute(
        """
        WITH claimable AS (
            SELECT id
            FROM agent.agent_jobs
            WHERE job_type = %s
              AND scheduled_at <= clock_timestamp()
              AND attempt_count < max_attempts
              AND (
                    status = 'queued'
                    OR (
                        status = 'running'
                        AND lease_expires_at < clock_timestamp()
                    )
              )
            -- 온디맨드는 사람이 화면을 보며 기다리는 요청이라 아침 브리핑보다
            -- 먼저 집는다. 둘 다 report_generation Job이고 Service가 priority를
            -- 넣지 않아 전부 기본값 100이라, 07:00에 아침 브리핑이 한꺼번에
            -- 쌓이면 그 뒤에 선다(2026-08-11 실측: 리포트 Job 224건이 전부
            -- priority=100. 워커 3대 × 건당 7분이면 27건 뒤는 63분을 기다린다).
            --
            -- priority를 앞에 그대로 두어 명세의 정렬 규칙은 유지한다. Service가
            -- 나중에 priority를 넣기 시작하면 그 값이 이 규칙보다 우선한다.
            ORDER BY
                priority DESC,
                -- COALESCE가 필요하다. report_type이 없는 Job은
                -- payload->>'report_type'이 NULL이고, NULL = 'ON_DEMAND'도 NULL이라
                -- DESC 정렬에서 NULLS FIRST로 맨 앞에 온다 — 온디맨드가 아닌 Job이
                -- 오히려 새치기한다. 빈 문자열로 낮춰 항상 true/false가 되게 한다.
                (COALESCE(payload->>'report_type', '') = 'ON_DEMAND') DESC,
                scheduled_at,
                created_at,
                id
            FOR UPDATE SKIP LOCKED
            LIMIT %s
        )
        UPDATE agent.agent_jobs AS job
        SET
            status = 'running',
            locked_at = clock_timestamp(),
            locked_by = %s,
            lease_expires_at = clock_timestamp() + (%s * interval '1 second'),
            started_at = COALESCE(started_at, clock_timestamp()),
            attempt_count = attempt_count + 1,
            progress = GREATEST(progress, %s),
            error_code = NULL,
            error_message = NULL
        FROM claimable
        WHERE job.id = claimable.id
        RETURNING
            job.id,
            job.user_id,
            job.feature_id,
            job.job_type,
            job.attempt_count,
            job.max_attempts,
            job.request_id,
            job.trace_id,
            job.payload
        """,
        (job_type, limit, worker_id, lease_seconds, claimed_progress),
    )
    rows = await cursor.fetchall()
    await wse_013("processing")
    jobs: list[ClaimedAgentJob] = []
    for row in rows:
        job = ClaimedAgentJob(
            job_id=str(row["id"]),
            user_id=row["user_id"],
            feature_id=row["feature_id"],
            job_type=row["job_type"],
            attempt_number=row["attempt_count"],
            max_attempts=row["max_attempts"],
            request_id=str(row["request_id"]) if row.get("request_id") else None,
            trace_id=str(row["trace_id"]) if row.get("trace_id") else None,
            payload=dict(row["payload"] or {}),
        )
        jobs.append(job)
        await _record_claimed_attempt(
            connection,
            job=job,
            worker_id=worker_id,
        )
        await connection.execute(
            """
            UPDATE agent.wiki_source_events
            SET status = 'processing', error_code = NULL, error_message = NULL
            WHERE job_id = %s
            """,
            (job.job_id,),
        )
    return jobs


async def reap_stalled_agent_jobs(
    connection: AsyncConnection[DictRow],
    *,
    limit: int,
) -> list[str]:
    """[JOB-009] 시도를 다 쓴 채 Lease가 만료된 running Job을 failed로 회수한다.

    claim_runnable_agent_jobs는 attempt_count < max_attempts인 Job만 다시
    집으므로, 마지막 시도의 Worker가 죽거나 Heartbeat 연장에 실패해 Lease가
    끊긴 Job은 이 조건 밖으로 밀려나 아무도 회수하지 못하고 running으로
    영구히 남는다 — 화면에는 "생성 중"이 멈춰 보인다. Scheduler tick이 이
    함수를 주기 호출해 그런 Job을 찾아 마감한다.

    후보는 SKIP LOCKED로 잠가 다른 Scheduler·Worker와 겹치지 않게 하고,
    job_009 판정으로 최종 확정한 뒤 Job·Attempt·연결된 wiki_source_events를
    함께 실패로 정리한다. Worker Lease 소유권(locked_by)이 이미 사라진
    Job이라 fail_agent_job과 달리 소유권 확인 없이 status로만 조건을 건다.

    Args:
        connection: 시스템 Scope가 설정된 DB 연결
        limit: 한 번에 회수할 최대 Job 수

    Returns:
        회수해 failed로 마감한 Job ID 목록
    """
    if not 1 <= limit <= 100:
        raise ValueError("JOB-009 회수 limit은 1에서 100 사이여야 합니다.")
    cursor = await connection.execute(
        """
        SELECT id, attempt_count, max_attempts, lease_expires_at
        FROM agent.agent_jobs
        WHERE status = 'running'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at < clock_timestamp()
          AND attempt_count >= max_attempts
        ORDER BY lease_expires_at
        FOR UPDATE SKIP LOCKED
        LIMIT %s
        """,
        (limit,),
    )
    candidates = await cursor.fetchall()
    now = datetime.now(UTC)
    reaped_ids: list[str] = []
    for row in candidates:
        snapshot = AgentJobLeaseSnapshot(
            status="running",
            attempt_count=int(row["attempt_count"]),
            max_attempts=int(row["max_attempts"]),
            lease_expires_at=row["lease_expires_at"],
        )
        if not await job_009(snapshot, now=now):
            continue
        job_id = str(row["id"])
        fail_cursor = await connection.execute(
            """
            UPDATE agent.agent_jobs
            SET
                status = 'failed',
                error_code = %s,
                error_message = %s,
                retryable = false,
                completed_at = clock_timestamp(),
                updated_at = clock_timestamp(),
                locked_at = NULL,
                locked_by = NULL,
                lease_expires_at = NULL
            WHERE id = %s AND status = 'running'
            RETURNING id
            """,
            (LEASE_TIMEOUT_ERROR_CODE, LEASE_TIMEOUT_ERROR_MESSAGE, job_id),
        )
        if await fail_cursor.fetchone() is None:
            continue
        await connection.execute(
            """
            UPDATE agent.agent_job_attempts
            SET
                status = 'timed_out',
                error_code = %s,
                error_message = %s,
                completed_at = clock_timestamp()
            WHERE job_id = %s AND status = 'running'
            """,
            (LEASE_TIMEOUT_ERROR_CODE, LEASE_TIMEOUT_ERROR_MESSAGE, job_id),
        )
        await connection.execute(
            """
            UPDATE agent.wiki_source_events
            SET
                status = 'failed',
                error_code = %s,
                error_message = %s,
                processed_at = clock_timestamp()
            WHERE job_id = %s
            """,
            (LEASE_TIMEOUT_ERROR_CODE, LEASE_TIMEOUT_ERROR_MESSAGE, job_id),
        )
        reaped_ids.append(job_id)
    return reaped_ids


async def claim_personal_wiki_jobs(
    connection: AsyncConnection[DictRow],
    *,
    worker_id: str,
    limit: int,
    lease_seconds: int,
) -> list[ClaimedAgentJob]:
    """실행 가능한 Personal Wiki Job을 SKIP LOCKED와 Lease로 점유한다."""
    return await claim_runnable_agent_jobs(
        connection,
        job_type="personal_wiki_build",
        worker_id=worker_id,
        limit=limit,
        lease_seconds=lease_seconds,
    )


async def extend_agent_job_lease(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    lease_seconds: int,
) -> datetime | None:
    """현재 Attempt를 소유한 Worker의 실행 중 Job Lease를 연장한다.

    Job ID와 Worker뿐 아니라 Attempt 번호까지 확인해, 같은 Worker ID가 다시
    점유한 새 Attempt를 이전 heartbeat가 잘못 연장하지 못하게 한다.
    """
    if not 30 <= lease_seconds <= 3600:
        raise ValueError("Job Lease는 30초에서 3600초 사이여야 합니다.")
    cursor = await connection.execute(
        """
        UPDATE agent.agent_jobs
        SET
            lease_expires_at = clock_timestamp() + (%s * interval '1 second'),
            updated_at = clock_timestamp()
        WHERE id = %s
          AND status = 'running'
          AND locked_by = %s
          AND attempt_count = %s
          AND lease_expires_at > clock_timestamp()
        RETURNING lease_expires_at
        """,
        (lease_seconds, job.job_id, worker_id, job.attempt_number),
    )
    row = await cursor.fetchone()
    if row is not None:
        return row["lease_expires_at"]
    completed_cursor = await connection.execute(
        """
        SELECT 1
        FROM agent.agent_job_attempts
        WHERE job_id = %s
          AND attempt_number = %s
          AND worker_id = %s
          AND status = 'completed'
        """,
        (job.job_id, job.attempt_number, worker_id),
    )
    if await completed_cursor.fetchone() is not None:
        return None
    raise RuntimeError(f"Job Lease 소유권이 없습니다: {job.job_id}")


async def get_agent_job(
    connection: AsyncConnection[DictRow], *, job_id: str
) -> StoredAgentJob | None:
    """Job ID로 현재 상태, 입력과 결과를 조회한다."""
    cursor = await connection.execute(
        """
        SELECT
            id,
            user_id,
            feature_id,
            job_type,
            idempotency_key,
            status,
            progress,
            COALESCE(request_id, '') AS request_id,
            payload,
            result,
            error_code,
            created_at,
            updated_at,
            completed_at
        FROM agent.agent_jobs
        WHERE id = %s
        """,
        (job_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _stored_agent_job(row)


async def get_agent_jobs(
    connection: AsyncConnection[DictRow], *, job_ids: list[str]
) -> list[StoredAgentJob]:
    """Job ID 목록의 현재 상태를 단일 SQL로 조회한다."""
    if not job_ids:
        return []
    cursor = await connection.execute(
        """
        SELECT
            id,
            user_id,
            feature_id,
            job_type,
            idempotency_key,
            status,
            progress,
            COALESCE(request_id, '') AS request_id,
            payload,
            result,
            error_code,
            created_at,
            updated_at,
            completed_at
        FROM agent.agent_jobs
        WHERE id = ANY(%s::uuid[])
        """,
        (job_ids,),
    )
    return [_stored_agent_job(row) for row in await cursor.fetchall()]


def _stored_agent_job(row: DictRow) -> StoredAgentJob:
    """PostgreSQL Row를 Agent Job 저장 레코드로 변환한다."""
    return StoredAgentJob(
        job_id=str(row["id"]),
        user_id=row["user_id"] or "",
        feature_id=row["feature_id"],
        job_type=row["job_type"],
        idempotency_key=row["idempotency_key"],
        status=row["status"],
        progress=int(row["progress"]),
        request_id=row["request_id"],
        payload=dict(row["payload"] or {}),
        result=(dict(row["result"]) if row["result"] is not None else None),
        error_code=row["error_code"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


async def list_runnable_agent_jobs(
    connection: AsyncConnection[DictRow],
    *,
    job_type: str,
    user_id: str | None = None,
    limit: int,
) -> list[str]:
    """실행 가능한 상태의 Agent Job ID를 우선순위 순서로 조회한다.

    Worker Batch Claim과 같은 조건(queued 또는 Lease가 만료된 running,
    scheduled_at 도래, 시도 횟수 여유)을 사용하되 Lock 없이 ID만 반환한다.
    실제 점유는 claim_agent_job_by_id가 수행하므로 조회 후 다른 Worker가
    먼저 가져가도 안전하다.

    Args:
        connection: 시스템 Scope가 설정된 DB 연결
        job_type: 조회할 Job 유형 (예: personal_wiki_build, personal_wiki_url)
        user_id: 특정 사용자의 Job만 조회할 때 지정
        limit: 반환할 최대 Job 수

    Returns:
        priority, scheduled_at, created_at 순으로 정렬된 Job ID 목록
    """
    if not 1 <= limit <= 100:
        raise ValueError("Job 조회 limit은 1에서 100 사이여야 합니다.")
    params: list[object] = [job_type]
    user_filter = ""
    if user_id is not None:
        user_filter = "AND user_id = %s"
        params.append(user_id)
    params.append(limit)
    cursor = await connection.execute(
        f"""
        SELECT id
        FROM agent.agent_jobs
        WHERE job_type = %s
          {user_filter}
          AND scheduled_at <= clock_timestamp()
          AND attempt_count < max_attempts
          AND (
                status = 'queued'
                OR (status = 'running' AND lease_expires_at < clock_timestamp())
          )
        ORDER BY priority DESC, scheduled_at, created_at, id
        LIMIT %s
        """,
        params,
    )
    rows = await cursor.fetchall()
    return [str(row["id"]) for row in rows]


async def claim_agent_job_by_id(
    connection: AsyncConnection[DictRow],
    *,
    job_id: str,
    worker_id: str,
    lease_seconds: int,
) -> ClaimedAgentJob | None:
    """개발 실행용으로 지정한 Job 하나를 Lease로 점유한다."""
    if not 30 <= lease_seconds <= 3600:
        raise ValueError("Job Lease는 30초에서 3600초 사이여야 합니다.")
    claimed_progress = await job_006(0, 5)
    cursor = await connection.execute(
        """
        UPDATE agent.agent_jobs
        SET
            status = 'running',
            locked_at = clock_timestamp(),
            locked_by = %s,
            lease_expires_at = clock_timestamp() + (%s * interval '1 second'),
            started_at = COALESCE(started_at, clock_timestamp()),
            attempt_count = attempt_count + 1,
            progress = GREATEST(progress, %s),
            error_code = NULL,
            error_message = NULL,
            updated_at = clock_timestamp()
        WHERE id = %s
          AND attempt_count < max_attempts
          AND (
                status = 'queued'
                OR (status = 'running' AND lease_expires_at < clock_timestamp())
          )
        RETURNING
            id,
            user_id,
            feature_id,
            job_type,
            attempt_count,
            max_attempts,
            payload
        """,
        (worker_id, lease_seconds, claimed_progress, job_id),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    job = ClaimedAgentJob(
        job_id=str(row["id"]),
        user_id=row["user_id"],
        feature_id=row["feature_id"],
        job_type=row["job_type"],
        attempt_number=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        payload=dict(row["payload"] or {}),
    )
    await _record_claimed_attempt(
        connection,
        job=job,
        worker_id=worker_id,
    )
    await connection.execute(
        """
        UPDATE agent.wiki_source_events
        SET status = 'processing', error_code = NULL, error_message = NULL,
            updated_at = clock_timestamp()
        WHERE job_id = %s
        """,
        (job.job_id,),
    )
    return job


async def complete_agent_job(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    result: dict[str, object],
) -> None:
    """Worker 소유권을 확인하고 Job·Attempt·Source Event를 완료 처리한다."""
    completed_progress = await job_006(5, 100)
    await wse_013("completed")
    cursor = await connection.execute(
        """
        UPDATE agent.agent_jobs
        SET
            status = 'completed',
            progress = %s,
            result = %s,
            retryable = false,
            completed_at = clock_timestamp(),
            updated_at = clock_timestamp(),
            locked_at = NULL,
            locked_by = NULL,
            lease_expires_at = NULL
        WHERE id = %s
          AND status = 'running'
          AND locked_by = %s
          AND lease_expires_at > clock_timestamp()
        RETURNING id
        """,
        (completed_progress, Jsonb(result), job.job_id, worker_id),
    )
    if await cursor.fetchone() is None:
        raise RuntimeError(f"Job Lease 소유권이 없습니다: {job.job_id}")
    await connection.execute(
        """
        UPDATE agent.agent_job_attempts
        SET status = 'completed', completed_at = clock_timestamp(), details = %s
        WHERE job_id = %s AND attempt_number = %s
        """,
        (Jsonb(result), job.job_id, job.attempt_number),
    )
    await connection.execute(
        """
        UPDATE agent.wiki_source_events
        SET status = 'completed', processed_at = clock_timestamp()
        WHERE job_id = %s
        """,
        (job.job_id,),
    )


async def defer_agent_job_for_provider(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    batch_item_id: str,
) -> None:
    """실행 Job을 waiting_provider로 바꾸고 Worker Lease를 즉시 해제한다."""
    cursor = await connection.execute(
        """
        UPDATE agent.agent_jobs
        SET status = 'waiting_provider',
            progress = GREATEST(progress, 80),
            result = %s,
            retryable = false,
            locked_at = NULL,
            locked_by = NULL,
            lease_expires_at = NULL,
            updated_at = clock_timestamp()
        WHERE id = %s
          AND status = 'running'
          AND locked_by = %s
          AND lease_expires_at > clock_timestamp()
        RETURNING id
        """,
        (Jsonb({"batch_item_id": batch_item_id}), job.job_id, worker_id),
    )
    if await cursor.fetchone() is None:
        raise RuntimeError(f"Job Lease 소유권이 없습니다: {job.job_id}")
    await connection.execute(
        """
        UPDATE agent.agent_job_attempts
        SET status = 'completed',
            completed_at = clock_timestamp(),
            details = %s
        WHERE job_id = %s AND attempt_number = %s
        """,
        (
            Jsonb({"status": "waiting_provider", "batch_item_id": batch_item_id}),
            job.job_id,
            job.attempt_number,
        ),
    )


async def complete_waiting_provider_job(
    connection: AsyncConnection[DictRow],
    *,
    job_id: str,
    user_id: str,
    result: Mapping[str, object],
) -> None:
    """도메인 결과 저장이 끝난 waiting_provider Job을 최종 완료 처리한다."""
    cursor = await connection.execute(
        """
        UPDATE agent.agent_jobs
        SET status = 'completed',
            progress = 100,
            result = %s,
            retryable = false,
            error_code = NULL,
            error_message = NULL,
            completed_at = clock_timestamp(),
            updated_at = clock_timestamp()
        WHERE id = %s::uuid
          AND user_id = %s
          AND status = 'waiting_provider'
        RETURNING id
        """,
        (Jsonb(dict(result)), job_id, user_id),
    )
    if await cursor.fetchone() is None:
        raise RuntimeError("완료할 waiting_provider Job을 찾지 못했습니다.")


async def fail_agent_job(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    error_code: str,
    error_message: str,
    retryable: bool,
    retry_delay_seconds: float | None = None,
) -> str:
    """Job 실패를 기록하고 재시도 가능 여부에 따라 다음 상태를 결정한다."""
    if retry_delay_seconds is not None and retry_delay_seconds < 0:
        raise ValueError("Job 재시도 대기시간은 0 이상이어야 합니다.")
    can_retry = retryable and job.attempt_number < job.max_attempts
    next_status = "queued" if can_retry else "failed"
    source_event_status = await wse_013("received" if can_retry else "failed")
    cursor = await connection.execute(
        """
        UPDATE agent.agent_jobs
        SET
            status = %s,
            error_code = %s,
            error_message = %s,
            retryable = %s,
            scheduled_at = CASE
                WHEN %s THEN clock_timestamp() + (%s * interval '1 second')
                ELSE scheduled_at
            END,
            completed_at = CASE WHEN %s THEN NULL ELSE clock_timestamp() END,
            updated_at = clock_timestamp(),
            locked_at = NULL,
            locked_by = NULL,
            lease_expires_at = NULL
        WHERE id = %s
          AND status = 'running'
          AND locked_by = %s
          AND lease_expires_at > clock_timestamp()
        RETURNING id
        """,
        (
            next_status,
            error_code,
            error_message[:2000],
            can_retry,
            can_retry,
            retry_delay_seconds or 0.0,
            can_retry,
            job.job_id,
            worker_id,
        ),
    )
    if await cursor.fetchone() is None:
        raise RuntimeError(f"Job Lease 소유권이 없습니다: {job.job_id}")
    await connection.execute(
        """
        UPDATE agent.agent_job_attempts
        SET
            status = 'failed',
            error_code = %s,
            error_message = %s,
            completed_at = clock_timestamp()
        WHERE job_id = %s AND attempt_number = %s
        """,
        (error_code, error_message[:2000], job.job_id, job.attempt_number),
    )
    await connection.execute(
        """
        UPDATE agent.wiki_source_events
        SET
            status = %s,
            retry_count = retry_count + 1,
            error_code = %s,
            error_message = %s,
            processed_at = CASE WHEN %s = 'failed' THEN clock_timestamp() ELSE NULL END
        WHERE job_id = %s
        """,
        (source_event_status, error_code, error_message[:2000], next_status, job.job_id),
    )
    return next_status


@dataclass(frozen=True, slots=True)
class EnqueuedWikiBuildJob:
    """원본 Version 하나에 대해 등록되거나 재사용된 Personal Wiki Build Job."""

    job_id: str
    created: bool


async def enqueue_personal_wiki_rebuild_job(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_event_id: str,
    source_event_row_id: str,
    removed_source_document_id: str,
    request_id: str | None = None,
    maintenance_pipeline_version: str = "legacy_v1",
) -> EnqueuedWikiBuildJob:
    """활성 원본 전체를 다시 읽는 Personal Wiki Full Rebuild Job을 멱등 등록한다.

    기존 Worker와 상태 조회 계약을 재사용하기 위해 Job 유형은
    ``personal_wiki_build``를 유지하고 Payload의 ``mode``로 전체 재빌드를 구분한다.
    """
    if maintenance_pipeline_version not in _MAINTENANCE_PIPELINE_VERSIONS:
        raise ValueError(
            "지원하지 않는 Wiki 유지 파이프라인 버전입니다: "
            f"{maintenance_pipeline_version}"
        )
    payload = {
        "mode": "full_rebuild",
        "trigger": "source_deleted",
        "maintenance_pipeline_version": maintenance_pipeline_version,
        "source_event_id": source_event_id,
        "source_event_row_id": source_event_row_id,
        "removed_source_document_id": removed_source_document_id,
    }
    creation = await job_001(
        feature_id="SVC-004",
        job_type="personal_wiki_build",
        user_id=user_id,
        idempotency_parts=[source_event_id, "full-rebuild"],
        payload=payload,
        request_id=request_id,
    )
    cursor = await connection.execute(
        """
        INSERT INTO agent.agent_jobs (
            feature_id,
            job_type,
            user_id,
            idempotency_key,
            status,
            progress,
            payload,
            retryable,
            request_id
        ) VALUES (%s, 'personal_wiki_build', %s, %s, 'queued', 0, %s, true, %s)
        ON CONFLICT (feature_id, COALESCE(user_id, ''), idempotency_key)
        DO NOTHING
        RETURNING id
        """,
        (
            creation.feature_id,
            creation.user_id,
            creation.idempotency_key,
            Jsonb(creation.payload),
            creation.request_id,
        ),
    )
    row = await cursor.fetchone()
    created = row is not None
    if row is None:
        cursor = await connection.execute(
            """
            SELECT id
            FROM agent.agent_jobs
            WHERE feature_id = %s
              AND COALESCE(user_id, '') = %s
              AND idempotency_key = %s
            """,
            (creation.feature_id, creation.user_id, creation.idempotency_key),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError(
                "멱등 충돌한 Personal Wiki Rebuild Job을 찾을 수 없습니다: "
                f"{creation.idempotency_key}"
            )
    job_id = str(row["id"])
    await connection.execute(
        """
        UPDATE agent.wiki_source_events
        SET job_id = %s
        WHERE id = %s
        """,
        (job_id, source_event_row_id),
    )
    return EnqueuedWikiBuildJob(job_id=job_id, created=created)


# 정기 유지보수 재구성 Job을 원본 제거 재구성과 구분하는 기능 ID.
# agent_jobs 멱등 Unique가 (feature_id, user_id, idempotency_key)라 ID를 나눠야
# 같은 날 두 경로가 서로의 Job을 재사용해 버리지 않는다.
MAINTENANCE_REBUILD_FEATURE_ID = "WBA-002"


async def list_users_for_maintenance_rebuild(
    connection: AsyncConnection[DictRow],
    *,
    stale_after_hours: float,
    limit: int,
    now: datetime | None = None,
) -> list[str]:
    """정기 Wiki 재구성이 필요한 사용자를 오래된 순서로 조회한다.

    증분 Build는 원본이 들어올 때만 돌아서 누적된 중복·고아 문서를 정리할
    기회가 없다. 이 조회는 마지막 정기 재구성이 오래된(또는 한 번도 없는)
    활성 Wiki 사용자를 고른다. 아직 대기·실행 중인 재구성이 있는 사용자는
    제외해 같은 사용자에게 재구성이 쌓이지 않게 한다.

    Args:
        connection: 이미 열린 agent-db 커넥션 (조회 Transaction은 내부에서 연다)
        stale_after_hours: 마지막 재구성으로부터 이 시간이 지나야 대상이 된다
        limit: 한 번에 가져올 최대 사용자 수
        now: 판정 기준 시각 (미지정 시 현재 UTC)

    Returns:
        재구성이 가장 시급한 순서의 사용자 ID 목록

    Raises:
        ValueError: stale_after_hours가 음수이거나 limit이 1 미만인 경우
    """
    if stale_after_hours < 0:
        raise ValueError("stale_after_hours는 0 이상이어야 합니다.")
    if limit < 1:
        raise ValueError("limit은 1 이상이어야 합니다.")
    moment = now or datetime.now(UTC)
    cutoff = moment - timedelta(hours=stale_after_hours)
    async with connection.transaction():
        await set_system_job_scope(connection)
        cursor = await connection.execute(
            """
            SELECT wiki.user_id
            FROM agent.wiki_versions AS wiki
            LEFT JOIN LATERAL (
                SELECT job.created_at, job.status
                FROM agent.agent_jobs AS job
                WHERE job.user_id = wiki.user_id
                  AND job.feature_id = %s
                ORDER BY job.created_at DESC
                LIMIT 1
            ) AS last_job ON TRUE
            WHERE wiki.status = 'active'
              AND (
                    last_job.created_at IS NULL
                 OR (
                        last_job.created_at < %s
                    AND last_job.status NOT IN ('queued', 'running')
                    )
              )
            ORDER BY last_job.created_at ASC NULLS FIRST, wiki.user_id ASC
            LIMIT %s
            """,
            (MAINTENANCE_REBUILD_FEATURE_ID, cutoff, limit),
        )
        rows = await cursor.fetchall()
    return [str(row["user_id"]) for row in rows]


async def enqueue_personal_wiki_maintenance_rebuild_job(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    maintenance_key: str,
    request_id: str | None = None,
    maintenance_pipeline_version: str = "legacy_v1",
) -> EnqueuedWikiBuildJob:
    """정기 유지보수용 Personal Wiki Full Rebuild Job을 멱등 등록한다.

    원본 제거로 도는 재구성(`enqueue_personal_wiki_rebuild_job`)과 달리 계기가 된
    Source Event가 없다. 따라서 이벤트 대신 주기 식별자로 멱등성을 잡고
    `wiki_source_events`도 건드리지 않는다. Job 유형과 Payload의 ``mode``는
    같은 값을 써서 기존 Worker와 상태 조회 계약을 그대로 재사용한다.

    Args:
        connection: 이미 열린 agent-db 커넥션
        user_id: 재구성 대상 사용자 ID
        maintenance_key: 같은 주기의 중복 등록을 막는 식별자 (예: "2026-08-10")
        request_id: 추적용 요청 ID

    Returns:
        등록되었거나 이미 존재하던 재구성 Job

    Raises:
        ValueError: maintenance_key가 비어 있는 경우
    """
    if not maintenance_key:
        raise ValueError("정기 재구성에 maintenance_key가 필요합니다.")
    if maintenance_pipeline_version not in _MAINTENANCE_PIPELINE_VERSIONS:
        raise ValueError(
            "지원하지 않는 Wiki 유지 파이프라인 버전입니다: "
            f"{maintenance_pipeline_version}"
        )
    payload = {
        "mode": "full_rebuild",
        "trigger": "maintenance",
        "maintenance_key": maintenance_key,
        "maintenance_pipeline_version": maintenance_pipeline_version,
    }
    creation = await job_001(
        feature_id=MAINTENANCE_REBUILD_FEATURE_ID,
        job_type="personal_wiki_build",
        user_id=user_id,
        idempotency_parts=[maintenance_key, "maintenance-rebuild"],
        payload=payload,
        request_id=request_id,
    )
    cursor = await connection.execute(
        """
        INSERT INTO agent.agent_jobs (
            feature_id,
            job_type,
            user_id,
            idempotency_key,
            status,
            progress,
            payload,
            retryable,
            request_id
        ) VALUES (%s, 'personal_wiki_build', %s, %s, 'queued', 0, %s, true, %s)
        ON CONFLICT (feature_id, COALESCE(user_id, ''), idempotency_key)
        DO NOTHING
        RETURNING id
        """,
        (
            creation.feature_id,
            creation.user_id,
            creation.idempotency_key,
            Jsonb(creation.payload),
            creation.request_id,
        ),
    )
    row = await cursor.fetchone()
    if row is not None:
        return EnqueuedWikiBuildJob(job_id=str(row["id"]), created=True)
    cursor = await connection.execute(
        """
        SELECT id
        FROM agent.agent_jobs
        WHERE feature_id = %s
          AND COALESCE(user_id, '') = %s
          AND idempotency_key = %s
        """,
        (creation.feature_id, creation.user_id, creation.idempotency_key),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError(
            "멱등 충돌한 정기 재구성 Job을 찾을 수 없습니다: "
            f"{creation.idempotency_key}"
        )
    return EnqueuedWikiBuildJob(job_id=str(row["id"]), created=False)


async def enqueue_personal_wiki_build_job(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_document_id: str,
    source_document_version_id: str,
    source_version: int,
    source_event_id: str,
    source_event_row_id: str | None = None,
    feature_id: str = "SVC-003",
    request_id: str | None = None,
    quiet_minutes: int = 0,
    max_wait_minutes: int = 30,
) -> EnqueuedWikiBuildJob:
    """저장된 사용자 원본 Version을 처리할 personal_wiki_build Job을 멱등 등록한다.

    SVC-003(URL 처리 요청)이 저장한 원본을 Personal Wiki Builder Worker가
    집어갈 수 있도록, 원본 저장과 같은 Transaction에서 호출한다(JOB-001).
    source_event_id + 원본 version 조합을 멱등성 키로 사용해 같은 요청이
    Job을 중복 생성하지 않고(JOB-010), 재수집으로 내용이 바뀌어 새 Version이
    생기면 그 Version만 처리하는 새 Job을 만든다.

    등록 직후 SCH-009 조용 시간(quiet window)을 적용한다(`defer_user_wiki_build_jobs`
    docstring이 지시하는 "새 원본이 수집될 때마다 호출" 지점). 웹 클리핑·온보딩
    시드·북마크·URL 수집 후속 저장이 모두 이 함수를 거치므로, 사용자가 짧은
    시간에 여러 건을 저장해도 대기 Job이 매번 따로 도는 대신 한 번으로 묶인다.

    Args:
        user_id: 원본을 소유한 사용자 ID
        source_document_id: user_source_documents Head ID
        source_document_version_id: 처리 대상 user_source_document_versions ID
        source_version: 처리 대상 원본 Version 번호
        source_event_id: Service 계층이 부여한 멱등 이벤트 식별자
        source_event_row_id: Job과 연결할 wiki_source_events Row ID
        feature_id: Job을 등록한 기능 ID (기본 SVC-003)
        quiet_minutes: 이번 저장 기준으로 대기 Job을 미루는 조용 시간(분)
        max_wait_minutes: 첫 대기 Job 발생 후 최대 대기시간(분)

    Returns:
        Job ID와 이번 호출에서 새로 생성됐는지 여부
    """
    payload = {
        "content_format": "markdown",
        "source_document_id": source_document_id,
        "source_document_version_id": source_document_version_id,
        "source_event_id": source_event_id,
        "source_event_row_id": source_event_row_id,
    }
    creation = await job_001(
        feature_id=feature_id,
        job_type="personal_wiki_build",
        user_id=user_id,
        idempotency_parts=[source_event_id, f"v{source_version}"],
        payload=payload,
        request_id=request_id,
    )
    cursor = await connection.execute(
        """
        INSERT INTO agent.agent_jobs (
            feature_id,
            job_type,
            user_id,
            idempotency_key,
            status,
            progress,
            payload,
            retryable,
            request_id
        ) VALUES (%s, 'personal_wiki_build', %s, %s, 'queued', 0, %s, true, %s)
        ON CONFLICT (feature_id, COALESCE(user_id, ''), idempotency_key)
        DO NOTHING
        RETURNING id
        """,
        (
            creation.feature_id,
            creation.user_id,
            creation.idempotency_key,
            Jsonb(creation.payload),
            creation.request_id,
        ),
    )
    row = await cursor.fetchone()
    created = row is not None
    if row is None:
        cursor = await connection.execute(
            """
            SELECT id
            FROM agent.agent_jobs
            WHERE feature_id = %s
              AND COALESCE(user_id, '') = %s
              AND idempotency_key = %s
            """,
            (creation.feature_id, creation.user_id, creation.idempotency_key),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError(
                "멱등 충돌한 Personal Wiki Job을 찾을 수 없습니다: "
                f"{creation.idempotency_key}"
            )
    job_id = str(row["id"])
    if source_event_row_id is not None:
        await connection.execute(
            """
            UPDATE agent.wiki_source_events
            SET job_id = %s
            WHERE id = %s
            """,
            (job_id, source_event_row_id),
        )
    await defer_user_wiki_build_jobs(
        connection,
        user_id=user_id,
        quiet_minutes=quiet_minutes,
        max_wait_minutes=max_wait_minutes,
    )
    return EnqueuedWikiBuildJob(job_id=job_id, created=created)


async def enqueue_url_collection_job(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_document_id: str,
    source_event_id: str,
    source_event_row_id: str,
    url: str,
    request_id: str,
) -> EnqueuedWikiBuildJob:
    """사용자 URL을 Markdown으로 수집할 비동기 Job을 멱등 등록한다."""
    payload = {
        "url": url,
        "source_document_id": source_document_id,
        "source_event_id": source_event_id,
        "source_event_row_id": source_event_row_id,
    }
    creation = await job_001(
        feature_id="SVC-003",
        job_type="personal_wiki_url",
        user_id=user_id,
        idempotency_parts=[source_event_id],
        payload=payload,
        request_id=request_id,
    )
    cursor = await connection.execute(
        """
        INSERT INTO agent.agent_jobs (
            feature_id,
            job_type,
            user_id,
            idempotency_key,
            status,
            progress,
            payload,
            retryable,
            request_id
        ) VALUES ('SVC-003', 'personal_wiki_url', %s, %s, 'queued', 0, %s, true, %s)
        ON CONFLICT (feature_id, COALESCE(user_id, ''), idempotency_key)
        DO NOTHING
        RETURNING id
        """,
        (
            creation.user_id,
            creation.idempotency_key,
            Jsonb(creation.payload),
            creation.request_id,
        ),
    )
    row = await cursor.fetchone()
    created = row is not None
    if row is None:
        cursor = await connection.execute(
            """
            SELECT id
            FROM agent.agent_jobs
            WHERE feature_id = 'SVC-003'
              AND COALESCE(user_id, '') = %s
              AND idempotency_key = %s
            """,
            (creation.user_id, creation.idempotency_key),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError(
                "멱등 충돌한 URL 수집 Job을 찾을 수 없습니다: "
                f"{creation.idempotency_key}"
            )
    job_id = str(row["id"])
    await connection.execute(
        """
        UPDATE agent.wiki_source_events
        SET job_id = %s, updated_at = clock_timestamp()
        WHERE id = %s
        """,
        (job_id, source_event_row_id),
    )
    return EnqueuedWikiBuildJob(job_id=job_id, created=created)


@dataclass(frozen=True, slots=True)
class EnqueuedCollectionRunJob:
    """수동 실행이 큐에 넣은 수집 실행 Job 하나."""

    job_id: str
    created: bool


async def enqueue_global_collection_run_job(
    connection: AsyncConnection[DictRow],
    *,
    source_key: str,
    request_id: str,
) -> EnqueuedCollectionRunJob:
    """수집 소스 하나를 백그라운드로 즉시 수집할 Job을 큐에 등록한다.

    수동 실행(SCH-021)은 이 Job만 큐에 넣고 바로 응답한다. 실제 수집은 수집
    Scheduler가 tick마다 이 Job을 집어(claim) 정기 수집과 같은 경로로 처리하므로,
    관심 Topic이 많아 오래 걸리는 소스도 HTTP 응답을 붙잡지 않는다.

    사용자 소속이 없는 시스템 Job이라 user_id는 NULL로 저장한다(그래서 user_id를
    필수로 요구하는 JOB-001 대신 멱등 Key(JOB-010)만 쓰고 직접 INSERT한다).
    request_id를 멱등 Key에 넣어 매 호출을 새 Job으로 남긴다 — 같은 소스를 다시
    눌렀을 때(이전 수집이 끝난 뒤에도) 새로 수집하도록 하기 위함이다.

    Args:
        connection: 시스템 Scope가 설정된 DB 연결
        source_key: 즉시 수집할 Source 식별 Key
        request_id: 이 요청을 추적하는 Request ID (멱등 Key로도 쓴다)

    Returns:
        Job ID와 이번 호출에서 새로 생성됐는지 여부
    """
    idempotency_key = await job_010([source_key, request_id])
    cursor = await connection.execute(
        """
        INSERT INTO agent.agent_jobs (
            feature_id,
            job_type,
            user_id,
            idempotency_key,
            status,
            progress,
            payload,
            retryable,
            request_id
        ) VALUES ('SCH-021', 'global_collection_run', NULL, %s, 'queued', 0, %s, false, %s)
        ON CONFLICT (feature_id, COALESCE(user_id, ''), idempotency_key)
        DO NOTHING
        RETURNING id
        """,
        (idempotency_key, Jsonb({"source_key": source_key}), request_id),
    )
    row = await cursor.fetchone()
    created = row is not None
    if row is None:
        cursor = await connection.execute(
            """
            SELECT id
            FROM agent.agent_jobs
            WHERE feature_id = 'SCH-021'
              AND COALESCE(user_id, '') = ''
              AND idempotency_key = %s
            """,
            (idempotency_key,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError(
                "멱등 충돌한 수집 실행 Job을 찾을 수 없습니다: "
                f"{idempotency_key}"
            )
    return EnqueuedCollectionRunJob(job_id=str(row["id"]), created=created)


async def defer_user_wiki_build_jobs(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    quiet_minutes: int,
    max_wait_minutes: int,
) -> int:
    """사용자의 대기 중 Wiki Build Job 실행 시각을 수집 조용 시간만큼 미룬다.

    새 원본이 수집될 때마다 호출해 모든 queued Job의 scheduled_at을
    `지금 + quiet_minutes`로 미루되, 가장 오래된 대기 Job의 created_at
    + max_wait_minutes를 넘지 않게 상한을 둔다. Worker Claim이
    scheduled_at <= now 조건을 사용하므로 이 값이 곧 Build 시작 시각이
    된다. 재시도 Backoff가 걸린 Job(attempt_count > 0)은 건드리지 않는다.

    Args:
        user_id: 원본을 수집한 사용자 ID
        quiet_minutes: 마지막 수집 후 Build를 미루는 시간(분)
        max_wait_minutes: 첫 대기 Job 발생 후 최대 대기시간(분)

    Returns:
        실행 시각이 조정된 Job 수
    """
    cursor = await connection.execute(
        """
        WITH pending AS (
            SELECT id, created_at
            FROM agent.agent_jobs
            WHERE job_type = 'personal_wiki_build'
              AND user_id = %s
              AND status = 'queued'
              AND attempt_count = 0
            FOR UPDATE
        ),
        horizon AS (
            SELECT min(created_at) AS first_created_at FROM pending
        )
        UPDATE agent.agent_jobs AS job
        SET
            scheduled_at = LEAST(
                horizon.first_created_at + (%s * interval '1 minute'),
                clock_timestamp() + (%s * interval '1 minute')
            ),
            updated_at = clock_timestamp()
        FROM pending, horizon
        WHERE job.id = pending.id
        RETURNING job.id
        """,
        (user_id, max_wait_minutes, quiet_minutes),
    )
    return len(await cursor.fetchall())


async def release_user_wiki_build_jobs(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
) -> int:
    """사용자의 대기 중 Wiki Build Job을 지금 즉시 실행 가능하게 만든다.

    "지금 Wiki에 반영" 강제 실행용으로, queued 상태 Job의 scheduled_at을
    현재 시각으로 당긴다. 재시도 Backoff가 걸린 Job도 함께 당긴다.

    Args:
        user_id: 강제 실행을 요청한 사용자 ID

    Returns:
        즉시 실행 가능으로 바뀐 Job 수
    """
    cursor = await connection.execute(
        """
        UPDATE agent.agent_jobs
        SET scheduled_at = clock_timestamp(), updated_at = clock_timestamp()
        WHERE job_type = 'personal_wiki_build'
          AND user_id = %s
          AND status = 'queued'
        RETURNING id
        """,
        (user_id,),
    )
    return len(await cursor.fetchall())


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def db_026(
    connection: AsyncConnection[DictRow], command: AgentJobStorageCommand
) -> list[ClaimedAgentJob] | str | None:
    """[DB-026] Agent Job 저장.

    비동기 작업 상태와 결과를 저장한다.
    """
    if isinstance(command, ClaimAgentJobsCommand):
        return await claim_runnable_agent_jobs(
            connection,
            job_type=command.job_type,
            worker_id=command.worker_id,
            limit=command.limit,
            lease_seconds=command.lease_seconds,
        )
    if isinstance(command, CompleteAgentJobCommand):
        await complete_agent_job(
            connection,
            job=command.job,
            worker_id=command.worker_id,
            result=command.result,
        )
        return None
    return await fail_agent_job(
        connection,
        job=command.job,
        worker_id=command.worker_id,
        error_code=command.error_code,
            error_message=command.error_message,
            retryable=command.retryable,
            retry_delay_seconds=command.retry_delay_seconds,
        )
