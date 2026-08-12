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
    JobInputError,
    ProviderRateLimitPolicy,
    wc_002,
    wc_003,
    wc_006,
    wc_007,
    wc_014,
)

type DictRow = dict[str, Any]
type JobProcessor = Callable[
    [AsyncConnection[DictRow], ClaimedAgentJob], Awaitable[dict[str, object]]
]
type JobSerializationKey = Callable[[ClaimedAgentJob], str | None]
type JobOperation = Callable[[], Awaitable[dict[str, object]]]

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


async def _lock_job_serialization_key(
    connection: AsyncConnection[DictRow],
    *,
    key: str,
) -> None:
    """외부 처리 동안 유지할 PostgreSQL 세션 Advisory Lock을 획득한다."""
    await connection.execute(
        "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
        (key,),
    )


async def _unlock_job_serialization_key(
    connection: AsyncConnection[DictRow],
    *,
    key: str,
) -> None:
    """Pool 반환 전에 PostgreSQL 세션 Advisory Lock을 명시적으로 해제한다."""
    cursor = await connection.execute(
        "SELECT pg_advisory_unlock(hashtextextended(%s, 0)) AS unlocked",
        (key,),
    )
    row = await cursor.fetchone()
    if row is not None and not bool(row.get("unlocked")):
        logger.warning("Job 직렬화 Advisory Lock이 이미 해제됐습니다: %s", key)


def _job_heartbeat_interval(lease_seconds: int) -> float:
    """Lease의 3분의 1 주기를 사용하되 DB 갱신 간격을 1~60초로 제한한다."""
    return max(1.0, min(60.0, lease_seconds / 3))


async def maintain_job_lease(
    pool: AsyncConnectionPool,
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    lease_seconds: int,
    stop_event: asyncio.Event,
    interval_seconds: float | None = None,
) -> None:
    """Job이 대기·실행되는 동안 별도 Pool 연결로 Claim Lease를 주기적으로 연장한다."""
    interval = (
        _job_heartbeat_interval(lease_seconds)
        if interval_seconds is None
        else interval_seconds
    )
    if interval <= 0:
        raise ValueError("Job heartbeat 간격은 0보다 커야 합니다.")
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            return
        except TimeoutError:
            async with pool.connection() as connection:
                async with connection.transaction():
                    await set_system_job_scope(connection)
                    expires_at = await wc_003(
                        connection,
                        job=job,
                        worker_id=worker_id,
                        lease_seconds=lease_seconds,
                    )
                    if expires_at is None:
                        return


async def _run_with_job_heartbeat(
    *,
    operation: JobOperation,
    heartbeat_task: asyncio.Task[None],
    stop_event: asyncio.Event,
) -> dict[str, object]:
    """heartbeat 실패 시 실행을 취소하고, 실행 완료 시 heartbeat를 즉시 정리한다."""
    if heartbeat_task.done():
        error = heartbeat_task.exception()
        if error is None:
            raise RuntimeError("Job heartbeat가 예기치 않게 종료됐습니다.")
        raise error
    operation_task = asyncio.create_task(operation())
    try:
        done, _ = await asyncio.wait(
            (operation_task, heartbeat_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Job 완료 SQL까지 성공했다면 동시 종료한 heartbeat의 소유권 오류보다
        # 완료 결과가 우선이다. Lease를 잃었다면 완료 SQL 자체가 실패한다.
        if operation_task in done:
            return operation_task.result()
        error = heartbeat_task.exception()
        if error is None:
            # Processor가 같은 Attempt를 완료해 heartbeat가 정상 종료한 경우다.
            # 완료 뒤 Advisory Lock 해제 같은 짧은 정리 작업은 끝까지 기다린다.
            return await operation_task
        raise error
    finally:
        stop_event.set()
        if not operation_task.done():
            operation_task.cancel()
        await asyncio.gather(
            operation_task,
            heartbeat_task,
            return_exceptions=True,
        )


async def record_job_failure(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    error: Exception,
    error_code_prefix: str,
) -> dict[str, object]:
    """Job 실패를 기록하고, 기록조차 못 해도 Batch 실행을 계속하게 한다.

    JobInputError만 입력 오류(_INPUT_INVALID, 재시도 불가)로 보고, 모델 출력
    파싱 오류 같은 일반 ValueError를 포함한 실행 오류에는 재시도 정책을 적용한다.
    Lease가 이미 만료돼 실패 기록의 소유권 검증에 걸리면(RuntimeError) Worker
    프로세스를 죽이는 대신 lease_lost 결과로 보고한다. 해당 Job은 Lease 만료 후
    다른 Claim이 다시 처리한다.
    """
    input_invalid = isinstance(error, JobInputError)
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
    serialization_key: JobSerializationKey | None = None,
    error_code_prefix: str,
    process: JobProcessor,
) -> list[dict[str, object]]:
    """지정 유형의 Job을 빈 실행 슬롯만큼 점유해 제한된 동시성으로 실행한다.

    Args:
        database_url: Agent DB 연결 문자열
        job_type: Claim할 Job 유형 (예: personal_wiki_build)
        worker_id: Job Lease 소유자 식별자
        limit: 한 번에 Claim할 최대 Job 수
        lease_seconds: Job Lease 유지 시간(초)
        concurrency: Claim한 Job을 동시에 실행할 최대 수
        rate_limit_policy: Job별 OpenAI 예상 요청·Token 예약 정책
        serialization_key: 같은 키의 Job을 Worker 프로세스 간 직렬화하는 함수
        error_code_prefix: 실패 오류 코드 접두사 (예: WIKI_BUILD)
        process: 점유한 Job 하나를 실행하는 함수 (connection, job)

    Returns:
        Job별 완료·실패·lease_lost 결과 목록
    """
    if limit < 1:
        raise ValueError("Job Batch limit은 1 이상이어야 합니다.")
    if concurrency < 1:
        raise ValueError("Job 실행 concurrency는 1 이상이어야 합니다.")
    pool = AsyncConnectionPool(
        conninfo=database_url,
        min_size=1,
        max_size=max(3, concurrency * 2 + 1),
        kwargs={"row_factory": dict_row},
        open=False,
    )
    await pool.open(wait=True)
    try:
        claim_lock = asyncio.Lock()
        claimed_count = 0
        queue_exhausted = False
        results_by_index: dict[int, dict[str, object]] = {}

        async def claim_next_job() -> tuple[int, ClaimedAgentJob] | None:
            """빈 실행 슬롯 하나가 처리할 다음 Job을 짧은 Transaction으로 점유한다."""
            nonlocal claimed_count, queue_exhausted
            async with claim_lock:
                if queue_exhausted or claimed_count >= limit:
                    return None
                async with pool.connection() as claim_connection:
                    async with claim_connection.transaction():
                        await set_system_job_scope(claim_connection)
                        jobs = await wc_002(
                            claim_connection,
                            job_type=job_type,
                            worker_id=worker_id,
                            limit=1,
                            lease_seconds=lease_seconds,
                        )
                if not jobs:
                    queue_exhausted = True
                    return None
                if len(jobs) != 1:
                    raise RuntimeError("단일 슬롯 Claim이 Job 하나를 초과했습니다.")
                index = claimed_count
                claimed_count += 1
                return index, jobs[0]

        async def process_claimed_job(job: ClaimedAgentJob) -> dict[str, object]:
            """점유한 Job 하나를 실행하고 완료·실패 결과로 변환한다."""
            stop_event = asyncio.Event()
            heartbeat_task = asyncio.create_task(
                maintain_job_lease(
                    pool,
                    job=job,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                    stop_event=stop_event,
                )
            )
            observations: list[LlmCallObservation] = []
            try:
                with capture_llm_calls() as observations:
                    async def operation() -> dict[str, object]:
                        """Provider 대기와 Job DB 연결 사용을 heartbeat 감시 안에서 실행한다."""
                        if rate_limit_policy is not None:
                            await wait_for_provider_capacity(
                                pool,
                                policy=rate_limit_policy,
                            )
                        async with pool.connection() as job_connection:
                            key = serialization_key(job) if serialization_key else None
                            if key:
                                await _lock_job_serialization_key(
                                    job_connection,
                                    key=key,
                                )
                            try:
                                return await process(job_connection, job)
                            finally:
                                if key:
                                    await _unlock_job_serialization_key(
                                        job_connection,
                                        key=key,
                                    )

                    result = await _run_with_job_heartbeat(
                        operation=operation,
                        heartbeat_task=heartbeat_task,
                        stop_event=stop_event,
                    )
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
            finally:
                stop_event.set()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            if rate_limit_policy is not None:
                await observe_job_provider_limits(
                    pool,
                    policy=rate_limit_policy,
                    observations=observations,
                )
            return {"job_id": job.job_id, "status": "completed", **result}

        async def run_slot() -> None:
            """한 실행 슬롯에서 Job 완료 직후 다음 Job을 동적으로 보충한다."""
            while True:
                claimed = await claim_next_job()
                if claimed is None:
                    return
                index, job = claimed
                results_by_index[index] = await process_claimed_job(job)

        await asyncio.gather(
            *(run_slot() for _ in range(min(concurrency, limit)))
        )
        return [results_by_index[index] for index in sorted(results_by_index)]
    finally:
        await pool.close()
