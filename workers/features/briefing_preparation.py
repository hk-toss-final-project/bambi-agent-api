"""아침 브리핑 주제 선정과 Wiki·Global·Live 근거 예열 Worker."""

from __future__ import annotations

import asyncio
from asyncio import to_thread
from datetime import date
from typing import Any

from psycopg import AsyncConnection

from agent.report_builder.api import (
    collect_live_context,
    merge_context_documents,
    report_022,
    run_wiki_read_graph_v2,
)
from app.services.briefing_topics import BriefingTopicsService
from domain.jobs.api import job_007
from infrastructure.persistence.api import (
    ClaimedAgentJob,
    CompleteAgentJobCommand,
    db_026,
    set_system_job_scope,
)
from infrastructure.persistence.postgres_wiki_graph import PostgresWikiGraphRepository
from shared.contracts import FeatureRequest
from workers.features.batch_runner import run_job_batch
from workers.runtime.api import JobInputError, ProviderRateLimitPolicy

type DictRow = dict[str, Any]

_MAX_PREWARM_LIVE_TOPICS = 3


def _briefing_serialization_key(job: ClaimedAgentJob) -> str:
    """같은 사용자의 같은 날짜 준비 Job을 Worker 프로세스 간 직렬화한다."""
    return (
        f"briefing_preparation:{job.user_id}:"
        f"{str(job.payload.get('briefing_date') or '')}"
    )


async def _collect_prepared_contexts(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
    topics: list[str],
    model: str,
) -> dict[str, list[Any]]:
    """Topic별 저장 근거를 먼저 읽고 부족한 Live 근거만 제한 병렬 수집한다."""
    outcomes: dict[str, Any] = {}
    contexts_by_topic: dict[str, list[Any]] = {}
    for topic in topics:
        outcome = await run_wiki_read_graph_v2(
            connection,
            topic=topic,
            user_id=user_id,
            model=model,
            job_id=job_id,
            defer_live=True,
        )
        outcomes[topic] = outcome
        contexts_by_topic[topic] = list(outcome.documents)

    live_topics = [
        topic
        for topic in topics
        if bool(getattr(outcomes[topic], "requires_live", False))
    ][:_MAX_PREWARM_LIVE_TOPICS]

    async def collect(topic: str) -> tuple[str, list[Any]]:
        """한 Topic의 Live 근거를 이벤트 루프 밖에서 수집한다."""
        documents = await to_thread(
            collect_live_context,
            topic,
            user_id,
            model=model,
        )
        return topic, documents

    if live_topics:
        for topic, live_documents in await asyncio.gather(
            *(collect(topic) for topic in live_topics)
        ):
            contexts_by_topic[topic] = merge_context_documents(
                contexts_by_topic[topic],
                live_documents,
            )
    return contexts_by_topic


async def _process_job(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    model: str,
    service: BriefingTopicsService,
) -> dict[str, object]:
    """브리핑 준비 Job 하나를 선정·근거 수집·Snapshot 저장 후 완료한다."""
    raw_date = str(job.payload.get("briefing_date") or "").strip()
    try:
        briefing_date = date.fromisoformat(raw_date)
    except ValueError as error:
        raise JobInputError("브리핑 준비 Job의 briefing_date가 잘못됐습니다.") from error
    limit = int(job.payload.get("limit") or 3)
    if not 1 <= limit <= 5:
        raise JobInputError("브리핑 준비 Job의 limit은 1에서 5 사이여야 합니다.")

    existing = await service.get_preparation_snapshot(
        job.user_id,
        briefing_date=briefing_date,
    )
    if existing is None:
        selection = await service.select_topics(job.user_id, limit=limit)
        contexts_by_topic = await _collect_prepared_contexts(
            connection,
            user_id=job.user_id,
            job_id=job.job_id,
            topics=selection.topics,
            model=model,
        )
        snapshot = await service.save_preparation(
            job.user_id,
            briefing_date=briefing_date,
            selection=selection,
            contexts_by_topic=contexts_by_topic,
            prepared_by_job_id=job.job_id,
        )
    else:
        snapshot = existing

    preparation_result = {
        "briefing_date": snapshot.briefing_date.isoformat(),
        "topics": list(snapshot.topics),
        "candidate_count": snapshot.candidate_count,
        "context_counts": {
            topic: len(contexts)
            for topic, contexts in snapshot.contexts_by_topic.items()
        },
    }
    prepared = await report_022(
        FeatureRequest(
            request_id=job.job_id,
            actor_id="briefing-preparation-worker",
            user_id=job.user_id,
            payload={"implementation": lambda: preparation_result},
        )
    )
    result = await job_007(dict(prepared.data))
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


async def run_briefing_preparation_batch(
    *,
    database_url: str,
    worker_id: str,
    limit: int = 1,
    concurrency: int = 1,
    rate_limit_policy: ProviderRateLimitPolicy | None = None,
    lease_seconds: int = 600,
    model: str = "gpt-4.1-mini",
) -> list[dict[str, object]]:
    """브리핑 준비 Job을 동적으로 점유해 제한된 동시성으로 실행한다."""
    repository = PostgresWikiGraphRepository(database_url)
    await repository.startup()
    service = BriefingTopicsService(repository)

    async def process(
        connection: AsyncConnection[DictRow], job: ClaimedAgentJob
    ) -> dict[str, object]:
        """공통 Batch 러너에 브리핑 준비 처리 함수를 연결한다."""
        return await _process_job(
            connection,
            job=job,
            worker_id=worker_id,
            model=model,
            service=service,
        )

    try:
        return await run_job_batch(
            database_url=database_url,
            job_type="briefing_preparation",
            worker_id=worker_id,
            limit=limit,
            lease_seconds=lease_seconds,
            concurrency=concurrency,
            rate_limit_policy=rate_limit_policy,
            serialization_key=_briefing_serialization_key,
            error_code_prefix="BRIEFING_PREPARATION",
            process=process,
        )
    finally:
        await repository.shutdown()
