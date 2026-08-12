"""PostgreSQL Report Builder Generation Worker.

Lease로 점유한 report_generation Job을 LangGraph 오케스트레이션
(agent.graph.run_report_generation)으로 실행해 검색·생성·영속화까지
저장한다. 개발 API(`/dev/.../report-generations`)와 같은 그래프를 사용한다.
"""

import logging
from datetime import date
from typing import Any

from psycopg import AsyncConnection

from agent.report_builder.api import (
    LEGACY_READ_PIPELINE_VERSION,
    READ_PIPELINE_VERSIONS,
    report_001,
    report_context_from_mapping,
    stage_report_generation_batch,
)
from agent.graph import run_report_generation
from domain.jobs.api import job_007
from infrastructure.persistence.api import (
    ClaimedAgentJob,
    CompleteAgentJobCommand,
    db_026,
    defer_agent_job_for_provider,
    load_briefing_topic_snapshot,
    set_personal_wiki_scope,
    set_system_job_scope,
)
from shared.contracts import FeatureRequest
from workers.features.batch_runner import run_job_batch
from workers.runtime.api import JobInputError, ProviderRateLimitPolicy

type DictRow = dict[str, Any]

logger = logging.getLogger("workers.report_generation")


async def _load_prewarmed_contexts(
    connection: AsyncConnection[DictRow],
    *,
    job: ClaimedAgentJob,
    topic: str,
    topics: list[str],
) -> dict[str, list[Any]]:
    """Job 날짜와 주제 목록이 일치하는 REPORT-022 근거 Snapshot을 복원한다."""
    raw_date = str(job.payload.get("briefing_date") or "").strip()
    if not raw_date:
        return {}
    try:
        briefing_date = date.fromisoformat(raw_date)
    except ValueError as error:
        raise JobInputError("Report Job의 briefing_date가 잘못됐습니다.") from error
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=job.user_id)
        snapshot = await load_briefing_topic_snapshot(
            connection,
            user_id=job.user_id,
            briefing_date=briefing_date,
        )
    if snapshot is None:
        logger.info(
            "브리핑 준비 Snapshot 없음, 일반 조사로 폴백: user=%s date=%s",
            job.user_id,
            briefing_date,
        )
        return {}
    requested_topics = topics or [topic]
    if list(snapshot.topics) != requested_topics:
        logger.warning(
            "브리핑 준비 주제 불일치, 일반 조사로 폴백: user=%s prepared=%s requested=%s",
            job.user_id,
            list(snapshot.topics),
            requested_topics,
        )
        return {}
    restored: dict[str, list[Any]] = {}
    try:
        for requested_topic in requested_topics:
            raw_contexts = snapshot.contexts_by_topic.get(requested_topic) or []
            contexts = [
                report_context_from_mapping(context) for context in raw_contexts
            ]
            if contexts:
                restored[requested_topic] = contexts
    except (TypeError, ValueError) as error:
        raise JobInputError(
            f"브리핑 준비 Snapshot Context가 잘못됐습니다: {error}"
        ) from error
    return restored


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
        raise JobInputError(
            "Report Builder Job Payload에 topic과 content_type이 필요합니다."
        )
    # 변경점 추적 토글. 개발 API(AgentWorkflowService)와 같은 키를 읽어야 요청이
    # 어느 경로로 실행되든 결과가 같다. 이 키가 없는 기존 Job(플래그 도입 이전
    # 등록분)은 지금까지와 같은 생성 경로로 실행된다.
    change_history_enabled = bool(job.payload.get("change_history_enabled") or False)
    generation_scope = str(job.payload.get("generation_scope") or "SINGLE_TOPIC")
    raw_interest_bundle = job.payload.get("interest_bundle")
    interest_bundle = (
        dict(raw_interest_bundle) if isinstance(raw_interest_bundle, dict) else None
    )
    if generation_scope == "INTEREST_BUNDLE" and interest_bundle is None:
        raise JobInputError(
            "INTEREST_BUNDLE Job Payload에 interest_bundle이 필요합니다."
        )
    if str(job.payload.get("execution_mode") or "sync") == "batch":
        if change_history_enabled:
            raise JobInputError(
                "변경점 추적 Report는 OpenAI Batch 실행을 지원하지 않습니다."
            )
        raw_contexts = job.payload.get("batch_contexts")
        if not isinstance(raw_contexts, list) or not raw_contexts:
            raise JobInputError(
                "Batch Report Job에는 고정 batch_contexts가 필요합니다."
            )
        try:
            contexts = [
                report_context_from_mapping(value)
                for value in raw_contexts
                if isinstance(value, dict)
            ]
        except (TypeError, ValueError) as error:
            raise JobInputError(
                f"Batch Report Context가 잘못됐습니다: {error}"
            ) from error
        if len(contexts) != len(raw_contexts):
            raise JobInputError(
                "Batch Report Context 중 객체가 아닌 값이 있습니다."
            )
        async with connection.transaction():
            await set_system_job_scope(connection)
            stored = await stage_report_generation_batch(
                connection,
                user_id=job.user_id,
                job_id=job.job_id,
                attempt_number=job.attempt_number,
                topic=topic,
                topics=topics,
                content_type=content_type,
                language=language,
                contexts=contexts,
                model=model,
                interest_bundle=interest_bundle,
            )
            await defer_agent_job_for_provider(
                connection,
                job=job,
                worker_id=worker_id,
                batch_item_id=stored.item_id,
            )
        return {
            "status": "waiting_provider",
            "batch_item_id": stored.item_id,
            "custom_id": stored.custom_id,
        }
    raw_topic_interest_bundles = job.payload.get("topic_interest_bundles")
    topic_interest_bundles = (
        {
            str(key): dict(value)
            for key, value in raw_topic_interest_bundles.items()
            if isinstance(value, dict)
        }
        if isinstance(raw_topic_interest_bundles, dict)
        else {}
    )
    wiki_version_id = str(job.payload.get("wiki_version_id") or "").strip() or None
    read_pipeline_version = str(
        job.payload.get("read_pipeline_version") or LEGACY_READ_PIPELINE_VERSION
    )
    if read_pipeline_version not in READ_PIPELINE_VERSIONS:
        raise JobInputError(
            "지원하지 않는 Wiki 읽기 파이프라인 버전입니다: "
            f"{read_pipeline_version}"
        )
    raw_navigation_snapshots = job.payload.get("wiki_navigation_snapshots")
    wiki_navigation_snapshots = (
        {
            str(key): dict(value)
            for key, value in raw_navigation_snapshots.items()
            if isinstance(value, dict)
        }
        if isinstance(raw_navigation_snapshots, dict)
        else {}
    )
    prewarmed_contexts_by_topic = await _load_prewarmed_contexts(
        connection,
        job=job,
        topic=topic,
        topics=topics,
    )
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
                    generation_scope=generation_scope,
                    interest_bundle=interest_bundle,
                    topic_interest_bundles=topic_interest_bundles,
                    wiki_version_id=wiki_version_id,
                    wiki_navigation_snapshots=wiki_navigation_snapshots,
                    read_pipeline_version=read_pipeline_version,
                    prewarmed_contexts_by_topic=prewarmed_contexts_by_topic,
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
    concurrency: int = 1,
    rate_limit_policy: ProviderRateLimitPolicy | None = None,
    lease_seconds: int = 600,
    model: str = "gpt-4.1-mini",
) -> list[dict[str, object]]:
    """Report Builder Job을 점유해 설정된 동시성으로 처리한다."""

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
        concurrency=concurrency,
        rate_limit_policy=rate_limit_policy,
        error_code_prefix="REPORT_GENERATION",
        process=process,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def worker_003(
    *,
    database_url: str,
    worker_id: str,
    limit: int = 1,
    concurrency: int = 1,
    rate_limit_policy: ProviderRateLimitPolicy | None = None,
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
        concurrency=concurrency,
        rate_limit_policy=rate_limit_policy,
        lease_seconds=lease_seconds,
        model=model,
    )
