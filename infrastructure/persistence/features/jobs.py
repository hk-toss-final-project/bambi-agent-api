"""Agent Job Claim·완료·실패 영속화.

Personal Wiki Worker가 PostgreSQL Job을 Lease로 점유하고, 각 시도의
결과와 최종 Job 상태를 멱등적으로 기록하는 DB-026 구현이다.
"""

from dataclasses import dataclass, field
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from shared.contracts import FeatureRequest, FeatureResult

type DictRow = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ClaimedAgentJob:
    """Worker가 Lease로 점유한 Agent Job 하나."""

    job_id: str
    user_id: str
    feature_id: str
    job_type: str
    attempt_number: int
    max_attempts: int
    payload: dict[str, Any] = field(default_factory=dict)


async def set_system_job_scope(connection: AsyncConnection[DictRow]) -> None:
    """Job Worker Transaction에 RLS 시스템 Scope를 설정한다."""
    await connection.execute("SET LOCAL app.access_scope = 'system'")


async def claim_personal_wiki_jobs(
    connection: AsyncConnection[DictRow],
    *,
    worker_id: str,
    limit: int,
    lease_seconds: int,
) -> list[ClaimedAgentJob]:
    """실행 가능한 Personal Wiki Job을 SKIP LOCKED와 Lease로 점유한다."""
    if not 1 <= limit <= 100:
        raise ValueError("Job Claim limit은 1에서 100 사이여야 합니다.")
    if not 30 <= lease_seconds <= 3600:
        raise ValueError("Job Lease는 30초에서 3600초 사이여야 합니다.")
    cursor = await connection.execute(
        """
        WITH claimable AS (
            SELECT id
            FROM agent.agent_jobs
            WHERE job_type = 'personal_wiki_build'
              AND scheduled_at <= clock_timestamp()
              AND attempt_count < max_attempts
              AND (
                    status = 'queued'
                    OR (
                        status = 'running'
                        AND lease_expires_at < clock_timestamp()
                    )
              )
            ORDER BY priority DESC, scheduled_at, created_at, id
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
            progress = GREATEST(progress, 5),
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
            job.payload
        """,
        (limit, worker_id, lease_seconds),
    )
    rows = await cursor.fetchall()
    jobs: list[ClaimedAgentJob] = []
    for row in rows:
        job = ClaimedAgentJob(
            job_id=str(row["id"]),
            user_id=row["user_id"],
            feature_id=row["feature_id"],
            job_type=row["job_type"],
            attempt_number=row["attempt_count"],
            max_attempts=row["max_attempts"],
            payload=dict(row["payload"] or {}),
        )
        jobs.append(job)
        await connection.execute(
            """
            INSERT INTO agent.agent_job_attempts (
                job_id,
                user_id,
                attempt_number,
                worker_id,
                status
            ) VALUES (%s, %s, %s, %s, 'running')
            ON CONFLICT (job_id, attempt_number) DO NOTHING
            """,
            (job.job_id, job.user_id, job.attempt_number, worker_id),
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


async def complete_agent_job(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    result: dict[str, object],
) -> None:
    """Worker 소유권을 확인하고 Job·Attempt·Source Event를 완료 처리한다."""
    cursor = await connection.execute(
        """
        UPDATE agent.agent_jobs
        SET
            status = 'completed',
            progress = 100,
            result = %s,
            retryable = false,
            completed_at = clock_timestamp(),
            locked_at = NULL,
            locked_by = NULL,
            lease_expires_at = NULL
        WHERE id = %s
          AND status = 'running'
          AND locked_by = %s
          AND lease_expires_at > clock_timestamp()
        RETURNING id
        """,
        (Jsonb(result), job.job_id, worker_id),
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


async def fail_agent_job(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    error_code: str,
    error_message: str,
    retryable: bool,
) -> str:
    """Job 실패를 기록하고 재시도 가능 여부에 따라 다음 상태를 결정한다."""
    can_retry = retryable and job.attempt_number < job.max_attempts
    next_status = "queued" if can_retry else "failed"
    cursor = await connection.execute(
        """
        UPDATE agent.agent_jobs
        SET
            status = %s,
            error_code = %s,
            error_message = %s,
            retryable = %s,
            scheduled_at = CASE
                WHEN %s THEN clock_timestamp() + (LEAST(300, POWER(2, attempt_count)) * interval '1 second')
                ELSE scheduled_at
            END,
            completed_at = CASE WHEN %s THEN NULL ELSE clock_timestamp() END,
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
        ("received" if can_retry else "failed", error_code, error_message[:2000], next_status, job.job_id),
    )
    return next_status


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def db_026(request: FeatureRequest) -> FeatureResult:
    """[DB-026] Agent Job 저장.

    비동기 작업 상태와 결과를 저장한다.
    """
    raise NotImplementedError("[DB-026] 기능 구현이 필요합니다.")
