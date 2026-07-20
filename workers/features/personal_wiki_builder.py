"""PostgreSQL Personal Wiki Builder Worker.

Lease로 점유한 personal_wiki_build Job을 LangGraph 오케스트레이션
(agent.graph.run_personal_wiki_build)으로 실행하고, 클리핑 원문을
개인 지식 Wiki 문서·Chunk·Embedding·Build Snapshot으로 저장한다.
"""

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from agent.graph import run_personal_wiki_build
from infrastructure.persistence.api import (
    ClaimedAgentJob,
    claim_personal_wiki_jobs,
    complete_agent_job,
    fail_agent_job,
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
    embedding_model: str,
) -> dict[str, object]:
    """점유한 Personal Wiki Job 하나를 그래프로 Build하고 완료 상태로 바꾼다."""
    source_version_id = job.payload.get("source_document_version_id")
    if not isinstance(source_version_id, str) or not source_version_id:
        raise ValueError("Job Payload에 source_document_version_id가 없습니다.")
    result = await run_personal_wiki_build(
        connection,
        user_id=job.user_id,
        source_document_version_id=source_version_id,
        job_id=job.job_id,
        model=model,
        embedding_model=embedding_model,
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


async def run_personal_wiki_batch(
    *,
    database_url: str,
    worker_id: str,
    limit: int = 1,
    lease_seconds: int = 600,
    model: str = "gpt-4.1-mini",
    embedding_model: str = "text-embedding-3-small",
) -> list[dict[str, object]]:
    """PostgreSQL에서 Personal Wiki Job Batch를 점유해 순차적으로 처리한다."""
    connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
    )
    try:
        async with connection.transaction():
            await set_system_job_scope(connection)
            jobs = await claim_personal_wiki_jobs(
                connection,
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
                    embedding_model=embedding_model,
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
    error_code = "WIKI_BUILD_RETRYABLE" if retryable else "WIKI_BUILD_INPUT_INVALID"
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
            "error_code": "WIKI_BUILD_LEASE_LOST",
            "error_message": f"{ownership_error} (원인: {str(error)[:200]})",
        }
    return {"job_id": job.job_id, "status": next_status, "error_code": error_code}


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def worker_002(request: FeatureRequest) -> FeatureResult:
    """[WORKER-002] 저장된 클리핑 Job을 개인 Wiki로 구성한다."""
    database_url = request.payload.get("database_url")
    worker_id = request.payload.get("worker_id", request.actor_id or "personal-wiki-worker")
    limit = request.payload.get("limit", 1)
    lease_seconds = request.payload.get("lease_seconds", 600)
    model = request.payload.get("model", "gpt-4.1-mini")
    embedding_model = request.payload.get(
        "embedding_model", "text-embedding-3-small"
    )
    if not isinstance(database_url, str) or not database_url:
        raise ValueError("WORKER-002에 database_url이 필요합니다.")
    if not isinstance(worker_id, str) or not worker_id:
        raise ValueError("WORKER-002에 worker_id가 필요합니다.")
    if not isinstance(limit, int) or not isinstance(lease_seconds, int):
        raise ValueError("WORKER-002의 limit과 lease_seconds는 정수여야 합니다.")
    if not isinstance(model, str) or not model:
        raise ValueError("WORKER-002의 model은 빈 문자열이면 안 됩니다.")
    if not isinstance(embedding_model, str) or not embedding_model:
        raise ValueError("WORKER-002의 embedding_model은 빈 문자열이면 안 됩니다.")
    results = await run_personal_wiki_batch(
        database_url=database_url,
        worker_id=worker_id,
        limit=limit,
        lease_seconds=lease_seconds,
        model=model,
        embedding_model=embedding_model,
    )
    return FeatureResult(
        feature_id="WORKER-002",
        data={"processed": len(results), "results": results},
    )
