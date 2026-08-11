"""Job 큐 Worker 공통 Batch 러너.

연결 생성 → Batch Claim → 건별 실행 → 완료·실패 기록의 공통 수명주기를
한 곳에서 구현한다. personal-wiki와 report-generation Worker는 Job 처리
함수와 오류 코드 접두사만 주입해 재사용하며, 실패 기록의 Lease 상실
복원력(lease_lost)도 여기서 한 번만 처리한다.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from psycopg.rows import dict_row
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from agent.llm.api import (
    is_retryable_openai_error,
    retry_after_seconds_from_error,
)
from infrastructure.persistence.api import (
    ClaimedAgentJob,
    set_system_job_scope,
)
from workers.runtime.api import wc_002, wc_006, wc_007, wc_013

type DictRow = dict[str, Any]
type JobProcessor = Callable[
    [AsyncConnection[DictRow], ClaimedAgentJob], Awaitable[dict[str, object]]
]


async def record_job_failure(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    error: Exception,
    error_code_prefix: str,
) -> dict[str, object]:
    """Job 실패를 기록하고, 기록조차 못 해도 Batch 실행을 계속하게 한다.

    ValueError는 입력 오류(_INPUT_INVALID, 재시도 불가)로, 그 외 예외는
    _RETRYABLE로 기록한다. Lease가 이미 만료돼 실패 기록의 소유권 검증에
    걸리면(RuntimeError) Worker 프로세스를 죽이는 대신 lease_lost 결과로
    보고한다. 해당 Job은 Lease 만료 후 다른 Claim이 다시 처리한다.
    """
    input_invalid = isinstance(error, ValueError)
    retryable = not input_invalid and is_retryable_openai_error(error)
    if input_invalid:
        error_code = f"{error_code_prefix}_INPUT_INVALID"
    elif retryable:
        error_code = f"{error_code_prefix}_RETRYABLE"
    else:
        error_code = f"{error_code_prefix}_PROVIDER_ACTION_REQUIRED"
    retry_delay_seconds = (
        await wc_007(
            job.attempt_number,
            retry_after_seconds=retry_after_seconds_from_error(error),
        )
        if retryable
        else None
    )
    try:
        async with connection.transaction():
            await set_system_job_scope(connection)
            next_status = await wc_006(
                connection,
                job=job,
                worker_id=worker_id,
                error_code=error_code,
                error_message=str(error),
                retryable=retryable,
                retry_delay_seconds=retry_delay_seconds,
            )
    except RuntimeError as ownership_error:
        return {
            "job_id": job.job_id,
            "status": "lease_lost",
            "error_code": f"{error_code_prefix}_LEASE_LOST",
            "error_message": f"{ownership_error} (원인: {str(error)[:200]})",
        }
    return {"job_id": job.job_id, "status": next_status, "error_code": error_code}


async def run_job_batch(
    *,
    database_url: str,
    job_type: str,
    worker_id: str,
    limit: int,
    lease_seconds: int,
    concurrency: int = 1,
    error_code_prefix: str,
    process: JobProcessor,
) -> list[dict[str, object]]:
    """지정 유형의 Job Batch를 점유해 제한된 동시성으로 실행한다.

    Args:
        database_url: Agent DB 연결 문자열
        job_type: Claim할 Job 유형 (예: personal_wiki_build)
        worker_id: Job Lease 소유자 식별자
        limit: 한 번에 Claim할 최대 Job 수
        lease_seconds: Job Lease 유지 시간(초)
        concurrency: Claim한 Job을 동시에 실행할 최대 수
        error_code_prefix: 실패 오류 코드 접두사 (예: WIKI_BUILD)
        process: 점유한 Job 하나를 실행하는 함수 (connection, job)

    Returns:
        Job별 완료·실패·lease_lost 결과 목록
    """
    if concurrency < 1:
        raise ValueError("Job 실행 concurrency는 1 이상이어야 합니다.")
    pool = AsyncConnectionPool(
        conninfo=database_url,
        min_size=1,
        max_size=max(2, concurrency + 1),
        kwargs={"row_factory": dict_row},
        open=False,
    )
    await pool.open(wait=True)
    try:
        async with pool.connection() as claim_connection:
            async with claim_connection.transaction():
                await set_system_job_scope(claim_connection)
                jobs = await wc_002(
                    claim_connection,
                    job_type=job_type,
                    worker_id=worker_id,
                    limit=limit,
                    lease_seconds=lease_seconds,
                )

        async def process_claimed_job(job: ClaimedAgentJob) -> dict[str, object]:
            """점유한 Job 하나를 실행하고 완료·실패 결과로 변환한다."""
            try:
                async with pool.connection() as job_connection:
                    result = await process(job_connection, job)
            except Exception as error:
                async with pool.connection() as failure_connection:
                    return await record_job_failure(
                        failure_connection,
                        job=job,
                        worker_id=worker_id,
                        error=error,
                        error_code_prefix=error_code_prefix,
                    )
            return {"job_id": job.job_id, "status": "completed", **result}

        return await wc_013(
            jobs,
            process_claimed_job,
            max_concurrency=concurrency,
        )
    finally:
        await pool.close()
