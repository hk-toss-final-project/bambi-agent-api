"""PostgreSQL Report Builder Generation Worker.

Lease로 점유한 report_generation Job을 LangGraph 오케스트레이션
(agent.graph.run_report_generation)으로 실행해 검색·생성·영속화까지
저장한다. 개발 API(`/dev/.../report-generations`)와 같은 그래프를 사용한다.
"""

from typing import Any

from psycopg import AsyncConnection

from agent.report_builder.api import report_001
from agent.graph import run_report_generation
from domain.jobs.api import job_007
from infrastructure.persistence.api import (
    ClaimedAgentJob,
    CompleteAgentJobCommand,
    db_026,
    set_system_job_scope,
)
from shared.contracts import FeatureRequest
from workers.features.batch_runner import run_job_batch

type DictRow = dict[str, Any]


async def _process_job(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    model: str,
) -> dict[str, object]:
    """점유한 Report Builder Job 하나를 그래프로 생성·저장하고 완료 상태로 바꾼다."""
    topic = str(job.payload.get("topic") or "").strip()
    topics = [
        str(value).strip()
        for value in (job.payload.get("topics") or [])
        if str(value).strip()
    ]
    content_type = str(job.payload.get("content_type") or "").strip()
    language = str(job.payload.get("language") or "ko").strip()
    if not topic or not content_type:
        raise ValueError("Report Builder Job Payload에 topic과 content_type이 필요합니다.")
    # 변경점 추적 토글. 개발 API(AgentWorkflowService)와 같은 키를 읽어야 요청이
    # 어느 경로로 실행되든 결과가 같다. 이 키가 없는 기존 Job(플래그 도입 이전
    # 등록분)은 지금까지와 같은 생성 경로로 실행된다.
    change_history_enabled = bool(job.payload.get("change_history_enabled") or False)
    feature_result = await report_001(
        FeatureRequest(
            request_id=job.job_id,
            actor_id=worker_id,
            user_id=job.user_id,
            payload={
                "implementation": lambda: run_report_generation(
                    connection,
                    user_id=job.user_id,
                    job_id=job.job_id,
                    attempt_number=job.attempt_number,
                    topic=topic,
                    topics=topics,
                    content_type=content_type,
                    language=language,
                    model=model,
                    change_history_enabled=change_history_enabled,
                )
            },
        )
    )
    result = await job_007(feature_result.data)
    async with connection.transaction():
        await set_system_job_scope(connection)
        await db_026(
            connection,
            CompleteAgentJobCommand(
                job=job,
                worker_id=worker_id,
                result=result,
            ),
        )
    return result


async def run_report_generation_batch(
    *,
    database_url: str,
    worker_id: str,
    limit: int = 1,
    lease_seconds: int = 600,
    model: str = "gpt-4.1-mini",
) -> list[dict[str, object]]:
    """PostgreSQL에서 Report Builder Generation Job Batch를 점유해 순차적으로 처리한다."""

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
        job_type="report_generation",
        worker_id=worker_id,
        limit=limit,
        lease_seconds=lease_seconds,
        error_code_prefix="REPORT_GENERATION",
        process=process,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def worker_003(
    *,
    database_url: str,
    worker_id: str,
    limit: int = 1,
    lease_seconds: int = 600,
    model: str = "gpt-4.1-mini",
) -> list[dict[str, object]]:
    """[WORKER-003] 생성 Job Batch를 점유하고 제한된 동시성으로 개인화 콘텐츠를 생성한다."""
    if not database_url:
        raise ValueError("WORKER-003에 database_url이 필요합니다.")
    if not worker_id:
        raise ValueError("WORKER-003에 worker_id가 필요합니다.")
    if not model:
        raise ValueError("WORKER-003의 model은 빈 문자열이면 안 됩니다.")
    return await run_report_generation_batch(
        database_url=database_url,
        worker_id=worker_id,
        limit=limit,
        lease_seconds=lease_seconds,
        model=model,
    )
