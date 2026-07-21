"""PostgreSQL Bambi Generation Worker.

Lease로 점유한 bambi_generation Job을 LangGraph 오케스트레이션
(agent.graph.run_bambi_generation)으로 실행해 검색·생성·영속화까지
저장한다. 개발 API(`/dev/.../bambi-generations`)와 같은 그래프를 사용한다.
"""

from typing import Any

from psycopg import AsyncConnection

from agent.bambi.api import bambi_001
from agent.graph import run_bambi_generation
from infrastructure.persistence.api import (
    ClaimedAgentJob,
    complete_agent_job,
    set_system_job_scope,
)
from shared.contracts import FeatureRequest, FeatureResult
from workers.features.batch_runner import run_job_batch

type DictRow = dict[str, Any]


async def _process_job(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    model: str,
) -> dict[str, object]:
    """점유한 Bambi Job 하나를 그래프로 생성·저장하고 완료 상태로 바꾼다."""
    topic = str(job.payload.get("topic") or "").strip()
    content_type = str(job.payload.get("content_type") or "").strip()
    language = str(job.payload.get("language") or "ko").strip()
    if not topic or not content_type:
        raise ValueError("Bambi Job Payload에 topic과 content_type이 필요합니다.")
    feature_result = await bambi_001(
        FeatureRequest(
            request_id=job.job_id,
            actor_id=worker_id,
            user_id=job.user_id,
            payload={
                "implementation": lambda: run_bambi_generation(
                    connection,
                    user_id=job.user_id,
                    job_id=job.job_id,
                    attempt_number=job.attempt_number,
                    topic=topic,
                    content_type=content_type,
                    language=language,
                    model=model,
                )
            },
        )
    )
    result = dict(feature_result.data)
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

    async def process(
        connection: AsyncConnection[DictRow], job: ClaimedAgentJob
    ) -> dict[str, object]:
        """공통 러너가 점유한 Job 하나를 생성 그래프로 처리한다."""
        return await _process_job(
            connection,
            job=job,
            worker_id=worker_id,
            model=model,
        )

    return await run_job_batch(
        database_url=database_url,
        job_type="bambi_generation",
        worker_id=worker_id,
        limit=limit,
        lease_seconds=lease_seconds,
        error_code_prefix="BAMBI_GENERATION",
        process=process,
    )


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
