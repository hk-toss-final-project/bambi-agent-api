"""Job 큐 Worker 공통 Batch 러너.

연결 생성 → Batch Claim → 건별 실행 → 완료·실패 기록의 공통 수명주기를
한 곳에서 구현한다. personal-wiki와 report-generation Worker는 Job 처리
함수와 오류 코드 접두사만 주입해 재사용하며, 실패 기록의 Lease 상실
복원력(lease_lost)도 여기서 한 번만 처리한다.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from agent.llm.api import (
    LlmCallObservation,
    capture_llm_calls,
    is_retryable_openai_error,
    response_headers_from_value,
    retry_after_seconds_from_error,
)
from infrastructure.persistence.api import (
    ClaimedAgentJob,
    observe_provider_rate_limits,
    set_system_job_scope,
)
from workers.runtime.api import (
    ProviderRateLimitPolicy,
    wc_002,
    wc_006,
    wc_007,
    wc_013,
    wc_014,
)

type DictRow = dict[str, Any]
type JobProcessor = Callable[
    [AsyncConnection[DictRow], ClaimedAgentJob], Awaitable[dict[str, object]]
]

logger = logging.getLogger("workers.batch_runner")


async def wait_for_provider_capacity(
    pool: AsyncConnectionPool,
    *,
    policy: ProviderRateLimitPolicy,
) -> None:
    """공유 RPM·TPM 용량이 생길 때까지 커넥션 밖에서 짧게 나눠 기다린다."""
    while True:
        async with pool.connection() as connection:
            async with connection.transaction():
                decision = await wc_014(connection, policy=policy)
        if decision.allowed:
            return
        if decision.retry_at is None:
            delay = 0.1
        else:
            delay = max(
                0.1,
                (decision.retry_at - datetime.now(UTC)).total_seconds(),
            )
        await asyncio.sleep(min(delay, policy.max_wait_slice_seconds))


def _latest_observed_headers(
    observations: Sequence[LlmCallObservation],
    error: Exception | None,
) -> tuple[Mapping[str, str], str | None]:
    """성공 응답 또는 실패 예외에서 가장 최근 Rate Limit 헤더를 고른다."""
    for observation in reversed(observations):
        if observation.headers:
            return observation.headers, observation.request_id
    if error is None:
        return {}, None
    headers = response_headers_from_value(error)
    return headers, headers.get("x-request-id")


async def observe_job_provider_limits(
    pool: AsyncConnectionPool,
    *,
    policy: ProviderRateLimitPolicy,
    observations: Sequence[LlmCallObservation],
    error: Exception | None = None,
) -> None:
    """Job의 최근 OpenAI 응답 헤더를 PostgreSQL Rate 상태에 반영한다."""
    headers, request_id = _latest_observed_headers(observations, error)
    if not headers:
        return
    try:
        async with pool.connection() as connection:
            async with connection.transaction():
                await observe_provider_rate_limits(
                    connection,
                    provider=policy.provider,
                    resource_key=policy.resource_key,
                    headers=headers,
                    request_id=request_id,
                    default_rpm=policy.default_rpm,
                    default_tpm=policy.default_tpm,
                )
    except Exception as observation_error:  # noqa: BLE001 - Job 결과를 보존한다
        logger.warning("Provider Rate Limit 응답 관찰 저장 실패: %s", observation_error)


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
    rate_limit_policy: ProviderRateLimitPolicy | None = None,
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
        rate_limit_policy: Job별 OpenAI 예상 요청·Token 예약 정책
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
            observations: list[LlmCallObservation] = []
            try:
                if rate_limit_policy is not None:
                    await wait_for_provider_capacity(pool, policy=rate_limit_policy)
                with capture_llm_calls() as observations:
                    async with pool.connection() as job_connection:
                        result = await process(job_connection, job)
            except Exception as error:
                if rate_limit_policy is not None:
                    await observe_job_provider_limits(
                        pool,
                        policy=rate_limit_policy,
                        observations=observations,
                        error=error,
                    )
                async with pool.connection() as failure_connection:
                    return await record_job_failure(
                        failure_connection,
                        job=job,
                        worker_id=worker_id,
                        error=error,
                        error_code_prefix=error_code_prefix,
                    )
            if rate_limit_policy is not None:
                await observe_job_provider_limits(
                    pool,
                    policy=rate_limit_policy,
                    observations=observations,
                )
            return {"job_id": job.job_id, "status": "completed", **result}

        return await wc_013(
            jobs,
            process_claimed_job,
            max_concurrency=concurrency,
        )
    finally:
        await pool.close()
