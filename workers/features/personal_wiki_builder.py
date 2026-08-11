"""PostgreSQL Personal Wiki Builder Worker.

Lease로 점유한 personal_wiki_build Job을 LangGraph 오케스트레이션
(agent.graph.run_personal_wiki_build)으로 실행하고, 클리핑 원문을
개인 지식 Wiki 문서·Chunk·Embedding·Build Snapshot으로 저장한다.
"""

from typing import Any

from psycopg import AsyncConnection

from agent.graph import run_personal_wiki_build, run_personal_wiki_rebuild
from agent.wiki_builder.api import wba_001
from domain.jobs.api import job_007
from infrastructure.persistence.api import (
    ClaimedAgentJob,
    CompleteAgentJobCommand,
    db_026,
    set_system_job_scope,
)
from workers.features.batch_runner import run_job_batch
from workers.runtime.api import ProviderRateLimitPolicy

type DictRow = dict[str, Any]


def _personal_wiki_serialization_key(job: ClaimedAgentJob) -> str:
    """같은 사용자의 Wiki Build를 직렬화할 Advisory Lock 키를 만든다."""
    return f"personal_wiki_build:{job.user_id}"


async def _process_job(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    model: str,
    embedding_batch_threshold: int,
) -> dict[str, object]:
    """점유한 Personal Wiki Job 하나를 그래프로 Build하고 완료 상태로 바꾼다."""
    if job.payload.get("mode") == "full_rebuild":
        result = await run_personal_wiki_rebuild(
            connection,
            user_id=job.user_id,
            job_id=job.job_id,
            model=model,
            embedding_batch_threshold=embedding_batch_threshold,
        )
    else:
        source_version_id = job.payload.get("source_document_version_id")
        if not isinstance(source_version_id, str) or not source_version_id:
            raise ValueError("Job Payload에 source_document_version_id가 없습니다.")
        result = await wba_001(
            run_personal_wiki_build,
            connection,
            user_id=job.user_id,
            source_document_version_id=source_version_id,
            job_id=job.job_id,
            model=model,
            embedding_batch_threshold=embedding_batch_threshold,
        )
    linked_result = await job_007(result)
    async with connection.transaction():
        await set_system_job_scope(connection)
        await db_026(
            connection,
            CompleteAgentJobCommand(
                job=job,
                worker_id=worker_id,
                result=linked_result,
            ),
        )
    return linked_result


async def run_personal_wiki_batch(
    *,
    database_url: str,
    worker_id: str,
    limit: int = 1,
    concurrency: int = 1,
    rate_limit_policy: ProviderRateLimitPolicy | None = None,
    lease_seconds: int = 600,
    model: str = "gpt-4.1-mini",
    embedding_batch_threshold: int = 0,
) -> list[dict[str, object]]:
    """Personal Wiki Job을 점유해 설정된 동시성으로 처리한다."""

    async def process(
        connection: AsyncConnection[DictRow], job: ClaimedAgentJob
    ) -> dict[str, object]:
        """공통 러너가 점유한 Job 하나를 Wiki Build 그래프로 처리한다."""
        return await _process_job(
            connection,
            job=job,
            worker_id=worker_id,
            model=model,
            embedding_batch_threshold=embedding_batch_threshold,
        )

    return await run_job_batch(
        database_url=database_url,
        job_type="personal_wiki_build",
        worker_id=worker_id,
        limit=limit,
        lease_seconds=lease_seconds,
        concurrency=concurrency,
        rate_limit_policy=rate_limit_policy,
        serialization_key=_personal_wiki_serialization_key,
        error_code_prefix="WIKI_BUILD",
        process=process,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def worker_002(
    *,
    database_url: str,
    worker_id: str,
    limit: int = 1,
    concurrency: int = 1,
    rate_limit_policy: ProviderRateLimitPolicy | None = None,
    lease_seconds: int = 600,
    model: str = "gpt-4.1-mini",
    embedding_batch_threshold: int = 0,
) -> list[dict[str, object]]:
    """[WORKER-002] 저장된 클리핑 Job을 개인 Wiki로 구성한다."""
    if not database_url:
        raise ValueError("WORKER-002에 database_url이 필요합니다.")
    if not worker_id:
        raise ValueError("WORKER-002에 worker_id가 필요합니다.")
    if not model:
        raise ValueError("WORKER-002의 model은 빈 문자열이면 안 됩니다.")
    return await run_personal_wiki_batch(
        database_url=database_url,
        worker_id=worker_id,
        limit=limit,
        concurrency=concurrency,
        rate_limit_policy=rate_limit_policy,
        lease_seconds=lease_seconds,
        model=model,
        embedding_batch_threshold=embedding_batch_threshold,
    )
