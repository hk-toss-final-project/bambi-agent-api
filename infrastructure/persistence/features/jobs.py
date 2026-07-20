"""Agent Job Claim·완료·실패 영속화.

Personal Wiki Worker가 PostgreSQL Job을 Lease로 점유하고, 각 시도의
결과와 최종 Job 상태를 멱등적으로 기록하는 DB-026 구현이다.
"""

from dataclasses import dataclass, field
from datetime import datetime
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
            progress = GREATEST(progress, 5),
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
        (worker_id, lease_seconds, job_id),
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
    cursor = await connection.execute(
        """
        UPDATE agent.agent_jobs
        SET
            status = 'completed',
            progress = 100,
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


@dataclass(frozen=True, slots=True)
class EnqueuedWikiBuildJob:
    """원본 Version 하나에 대해 등록되거나 재사용된 Personal Wiki Build Job."""

    job_id: str
    created: bool


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
) -> EnqueuedWikiBuildJob:
    """저장된 사용자 원본 Version을 처리할 personal_wiki_build Job을 멱등 등록한다.

    SVC-003(URL 처리 요청)이 저장한 원본을 Personal Wiki Builder Worker가
    집어갈 수 있도록, 원본 저장과 같은 Transaction에서 호출한다(JOB-001).
    source_event_id + 원본 version 조합을 멱등성 키로 사용해 같은 요청이
    Job을 중복 생성하지 않고(JOB-010), 재수집으로 내용이 바뀌어 새 Version이
    생기면 그 Version만 처리하는 새 Job을 만든다.

    Args:
        user_id: 원본을 소유한 사용자 ID
        source_document_id: user_source_documents Head ID
        source_document_version_id: 처리 대상 user_source_document_versions ID
        source_version: 처리 대상 원본 Version 번호
        source_event_id: Service 계층이 부여한 멱등 이벤트 식별자
        source_event_row_id: Job과 연결할 wiki_source_events Row ID
        feature_id: Job을 등록한 기능 ID (기본 SVC-003)

    Returns:
        Job ID와 이번 호출에서 새로 생성됐는지 여부
    """
    idempotency_key = f"{source_event_id}:v{source_version}"
    payload = {
        "content_format": "markdown",
        "source_document_id": source_document_id,
        "source_document_version_id": source_document_version_id,
        "source_event_id": source_event_id,
        "source_event_row_id": source_event_row_id,
    }
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
        (feature_id, user_id, idempotency_key, Jsonb(payload), request_id),
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
            (feature_id, user_id, idempotency_key),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError(
                f"멱등 충돌한 Personal Wiki Job을 찾을 수 없습니다: {idempotency_key}"
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
        (user_id, source_event_id, Jsonb(payload), request_id),
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
            (user_id, source_event_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError(
                f"멱등 충돌한 URL 수집 Job을 찾을 수 없습니다: {source_event_id}"
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
async def db_026(request: FeatureRequest) -> FeatureResult:
    """[DB-026] Agent Job 저장.

    비동기 작업 상태와 결과를 저장한다.
    """
    raise NotImplementedError("[DB-026] 기능 구현이 필요합니다.")
