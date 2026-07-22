"""Job 큐 Worker 공통 Batch 러너.

연결 생성 → Batch Claim → 건별 실행 → 완료·실패 기록의 공통 수명주기를
한 곳에서 구현한다. personal-wiki와 bambi-generation Worker는 Job 처리
함수와 오류 코드 접두사만 주입해 재사용하며, 실패 기록의 Lease 상실
복원력(lease_lost)도 여기서 한 번만 처리한다.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from infrastructure.persistence.api import (
    ClaimedAgentJob,
    set_system_job_scope,
)
from workers.runtime.api import wc_002, wc_006, wc_013

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
    retryable = not isinstance(error, ValueError)
    error_code = (
        f"{error_code_prefix}_RETRYABLE"
        if retryable
        else f"{error_code_prefix}_INPUT_INVALID"
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
    error_code_prefix: str,
    process: JobProcessor,
) -> list[dict[str, object]]:
    """지정 유형의 Job Batch를 점유해 순차 실행하고 결과 목록을 반환한다.

    Args:
        database_url: Agent DB 연결 문자열
        job_type: Claim할 Job 유형 (예: personal_wiki_build)
        worker_id: Job Lease 소유자 식별자
        limit: 한 번에 Claim할 최대 Job 수
        lease_seconds: Job Lease 유지 시간(초)
        error_code_prefix: 실패 오류 코드 접두사 (예: WIKI_BUILD)
        process: 점유한 Job 하나를 실행하는 함수 (connection, job)

    Returns:
        Job별 완료·실패·lease_lost 결과 목록
    """
    connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
    )
    try:
        async with connection.transaction():
            await set_system_job_scope(connection)
            jobs = await wc_002(
                connection,
                job_type=job_type,
                worker_id=worker_id,
                limit=limit,
                lease_seconds=lease_seconds,
            )
        async def process_claimed_job(job: ClaimedAgentJob) -> dict[str, object]:
            """점유한 Job 하나를 실행하고 완료·실패 결과로 변환한다."""
            try:
                result = await process(connection, job)
            except Exception as error:
                return await record_job_failure(
                    connection,
                    job=job,
                    worker_id=worker_id,
                    error=error,
                    error_code_prefix=error_code_prefix,
                )
            return {"job_id": job.job_id, "status": "completed", **result}

        return await wc_013(jobs, process_claimed_job)
    finally:
        await connection.close()
