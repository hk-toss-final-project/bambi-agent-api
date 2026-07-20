"""PostgreSQL Bambi Generation Worker.

Lease로 점유한 bambi_generation Job을 각각 독립적으로 실행하고,
개인 Wiki·Global 최신 문서 검색 Context로 콘텐츠를 생성해
생성 Run·후보·Citation·Publish Snapshot(ready)·Outbox까지 저장한다.
개발 API(`/dev/.../bambi-generations`)와 같은 Handler 체인을 사용한다.
"""

from asyncio import to_thread
from time import monotonic
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent.bambi.api import generate_bambi_content
from infrastructure.persistence.api import (
    ClaimedAgentJob,
    claim_runnable_agent_jobs,
    complete_agent_job,
    fail_agent_job,
    load_bambi_context,
    persist_bambi_generation,
    set_personal_wiki_scope,
    set_system_job_scope,
)
from shared.contracts import FeatureRequest, FeatureResult

type DictRow = dict[str, Any]


async def _process_job(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    model: str,
) -> dict[str, object]:
    """점유한 Bambi Job 하나를 생성·저장하고 완료 상태로 바꾼다.

    검색과 결과 저장은 각각 짧은 Transaction으로 분리하고, LLM 호출은
    Transaction 밖에서 실행해 Connection과 Row Lock을 길게 잡지 않는다.
    """
    topic = str(job.payload.get("topic") or "").strip()
    content_type = str(job.payload.get("content_type") or "").strip()
    language = str(job.payload.get("language") or "ko").strip()
    if not topic or not content_type:
        raise ValueError("Bambi Job Payload에 topic과 content_type이 필요합니다.")
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=job.user_id)
        contexts = await load_bambi_context(
            connection,
            user_id=job.user_id,
            query=topic,
        )
    started = monotonic()
    generated = await to_thread(
        generate_bambi_content,
        topic=topic,
        content_type=content_type,
        language=language,
        contexts=contexts,
        model=model,
    )
    latency_ms = int((monotonic() - started) * 1000)
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=job.user_id)
        result = await persist_bambi_generation(
            connection,
            job_id=job.job_id,
            user_id=job.user_id,
            attempt_number=job.attempt_number,
            content_type=content_type,
            generated=generated,
            contexts=contexts,
            latency_ms=latency_ms,
        )
    async with connection.transaction():
        await set_system_job_scope(connection)
        await complete_agent_job(
            connection,
            job=job,
            worker_id=worker_id,
            result=result,
        )
    return result


async def run_bambi_generation_batch(
    *,
    database_url: str,
    worker_id: str,
    limit: int = 1,
    lease_seconds: int = 600,
    model: str = "gpt-4.1-mini",
) -> list[dict[str, object]]:
    """PostgreSQL에서 Bambi Generation Job Batch를 점유해 순차적으로 처리한다."""
    connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
    )
    try:
        async with connection.transaction():
            await set_system_job_scope(connection)
            jobs = await claim_runnable_agent_jobs(
                connection,
                job_type="bambi_generation",
                worker_id=worker_id,
                limit=limit,
                lease_seconds=lease_seconds,
            )
        results: list[dict[str, object]] = []
        for job in jobs:
            try:
                result = await _process_job(
                    connection,
                    job=job,
                    worker_id=worker_id,
                    model=model,
                )
            except Exception as error:
                results.append(
                    await _record_job_failure(
                        connection,
                        job=job,
                        worker_id=worker_id,
                        error=error,
                    )
                )
            else:
                results.append({"job_id": job.job_id, "status": "completed", **result})
        return results
    finally:
        await connection.close()


async def _record_job_failure(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    error: Exception,
) -> dict[str, object]:
    """Job 실패를 기록하고, 기록조차 못 해도 Batch 실행을 계속하게 한다.

    Lease가 이미 만료돼 실패 기록의 소유권 검증에 걸리면(RuntimeError)
    Worker 프로세스를 죽이는 대신 lease_lost 결과로 보고한다. 해당 Job은
    Lease 만료 후 다른 Claim이 다시 처리하거나 관리자 수동 복구 대상이 된다.
    """
    retryable = not isinstance(error, ValueError)
    error_code = (
        "BAMBI_GENERATION_RETRYABLE" if retryable else "BAMBI_GENERATION_INPUT_INVALID"
    )
    try:
        async with connection.transaction():
            await set_system_job_scope(connection)
            next_status = await fail_agent_job(
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
            "error_code": "BAMBI_GENERATION_LEASE_LOST",
            "error_message": f"{ownership_error} (원인: {str(error)[:200]})",
        }
    return {"job_id": job.job_id, "status": next_status, "error_code": error_code}


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def worker_003(request: FeatureRequest) -> FeatureResult:
    """[WORKER-003] 생성 Job Batch를 점유하고 제한된 동시성으로 개인화 콘텐츠를 생성한다."""
    database_url = request.payload.get("database_url")
    worker_id = request.payload.get(
        "worker_id", request.actor_id or "bambi-generation-worker"
    )
    limit = request.payload.get("limit", 1)
    lease_seconds = request.payload.get("lease_seconds", 600)
    model = request.payload.get("model", "gpt-4.1-mini")
    if not isinstance(database_url, str) or not database_url:
        raise ValueError("WORKER-003에 database_url이 필요합니다.")
    if not isinstance(worker_id, str) or not worker_id:
        raise ValueError("WORKER-003에 worker_id가 필요합니다.")
    if not isinstance(limit, int) or not isinstance(lease_seconds, int):
        raise ValueError("WORKER-003의 limit과 lease_seconds는 정수여야 합니다.")
    if not isinstance(model, str) or not model:
        raise ValueError("WORKER-003의 model은 빈 문자열이면 안 됩니다.")
    results = await run_bambi_generation_batch(
        database_url=database_url,
        worker_id=worker_id,
        limit=limit,
        lease_seconds=lease_seconds,
        model=model,
    )
    return FeatureResult(
        feature_id="WORKER-003",
        data={"processed": len(results), "results": results},
    )
