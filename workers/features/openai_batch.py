"""PostgreSQL 대기 Item을 OpenAI Batch로 제출하고 결과를 수거하는 Worker."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent.llm.api import BatchProvider, OpenAIBatchProvider
from infrastructure.persistence.api import (
    DueLlmBatch,
    ClaimedBatchResultItem,
    ProviderBatchSnapshot,
    apply_llm_batch_result_lines,
    claim_due_llm_batches,
    claim_llm_batch,
    claim_unapplied_batch_results,
    mark_batch_result_applied,
    mark_llm_batch_submitted,
    release_failed_llm_batch_submission,
    release_batch_result_application,
    set_system_job_scope,
    update_llm_batch_snapshot,
)

type ProviderFactory = Callable[[], BatchProvider]
type CycleObserver = Callable[[list[dict[str, object]]], None]
type ResultHandler = Callable[[Any, ClaimedBatchResultItem], Awaitable[object]]


async def _claim_submission(
    pool: AsyncConnectionPool,
    *,
    max_items: int,
) -> Any:
    """외부 호출 전에 제출할 로컬 Batch 하나를 짧은 Transaction으로 점유한다."""
    async with pool.connection() as connection:
        async with connection.transaction():
            await set_system_job_scope(connection)
            return await claim_llm_batch(connection, max_items=max_items)


async def _submit_batch(
    pool: AsyncConnectionPool,
    *,
    provider: BatchProvider,
    max_items: int,
    poll_interval_seconds: int,
) -> dict[str, object] | None:
    """로컬 Batch 하나를 Provider에 제출하고 성공·실패 상태를 저장한다."""
    batch = await _claim_submission(pool, max_items=max_items)
    if batch is None:
        return None
    try:
        submission = await provider.submit(batch)
    except Exception as error:  # noqa: BLE001 - 제출 실패를 Item 재시도로 전환한다
        async with pool.connection() as connection:
            async with connection.transaction():
                await set_system_job_scope(connection)
                await release_failed_llm_batch_submission(
                    connection,
                    batch_id=batch.batch_id,
                    error=str(error),
                )
        return {
            "batch_id": batch.batch_id,
            "status": "submission_failed",
            "item_count": len(batch.items),
            "error": str(error),
        }
    async with pool.connection() as connection:
        async with connection.transaction():
            await set_system_job_scope(connection)
            await mark_llm_batch_submitted(
                connection,
                batch_id=batch.batch_id,
                provider_batch_id=submission.provider_batch_id,
                input_file_id=submission.input_file_id,
                initial_status=submission.status,
                poll_after_seconds=poll_interval_seconds,
            )
    return {
        "batch_id": batch.batch_id,
        "provider_batch_id": submission.provider_batch_id,
        "status": submission.status,
        "item_count": len(batch.items),
    }


async def _claim_due_polls(
    pool: AsyncConnectionPool,
    *,
    limit: int,
    poll_lease_seconds: int,
) -> list[DueLlmBatch]:
    """상태 조회 시각이 된 Batch를 Poll Lease로 점유한다."""
    async with pool.connection() as connection:
        async with connection.transaction():
            await set_system_job_scope(connection)
            return await claim_due_llm_batches(
                connection,
                limit=limit,
                poll_lease_seconds=poll_lease_seconds,
            )


async def _download_terminal_lines(
    provider: BatchProvider,
    snapshot: ProviderBatchSnapshot,
) -> list[dict[str, object]]:
    """완료·실패 Batch의 output과 error 파일을 모두 내려받아 합친다."""
    lines: list[dict[str, object]] = []
    if snapshot.output_file_id:
        lines.extend(await provider.download_jsonl(snapshot.output_file_id))
    if snapshot.error_file_id:
        lines.extend(await provider.download_jsonl(snapshot.error_file_id))
    return lines


async def _poll_batch(
    pool: AsyncConnectionPool,
    *,
    provider: BatchProvider,
    batch: DueLlmBatch,
    poll_interval_seconds: int,
) -> dict[str, object]:
    """Provider 상태를 조회하고 terminal이면 custom_id별 결과까지 반영한다."""
    try:
        snapshot = await provider.retrieve(batch.provider_batch_id)
        terminal = snapshot.status in {"completed", "failed", "expired", "cancelled"}
        lines = await _download_terminal_lines(provider, snapshot) if terminal else []
    except Exception as error:  # noqa: BLE001 - Poll Lease 만료 뒤 다시 조회한다
        return {
            "batch_id": batch.batch_id,
            "provider_batch_id": batch.provider_batch_id,
            "status": "poll_failed",
            "error": str(error),
        }
    async with pool.connection() as connection:
        async with connection.transaction():
            await set_system_job_scope(connection)
            await update_llm_batch_snapshot(
                connection,
                batch_id=batch.batch_id,
                snapshot=snapshot,
                poll_after_seconds=poll_interval_seconds,
            )
            counts = (
                await apply_llm_batch_result_lines(
                    connection,
                    batch_id=batch.batch_id,
                    lines=lines,
                    terminal_status=snapshot.status,
                )
                if terminal
                else {"completed": 0, "failed": 0, "requeued": 0}
            )
    return {
        "batch_id": batch.batch_id,
        "provider_batch_id": batch.provider_batch_id,
        "status": snapshot.status,
        **counts,
    }


def _default_result_handlers() -> dict[str, ResultHandler]:
    """workload별 도메인 결과 반영 함수를 공개 facade에서 구성한다."""
    from agent.wiki_builder.api import apply_wiki_embedding_batch_result
    from agent.report_builder.api import apply_report_generation_batch_result

    return {
        "wiki_embedding": apply_wiki_embedding_batch_result,
        "report_generation": apply_report_generation_batch_result,
    }


async def _apply_domain_results(
    pool: AsyncConnectionPool,
    *,
    worker_id: str,
    limit: int,
    lease_seconds: int,
    handlers: Mapping[str, ResultHandler],
) -> list[dict[str, object]]:
    """완료 Item을 Lease로 점유해 workload Handler로 멱등 반영한다."""
    async with pool.connection() as claim_connection:
        async with claim_connection.transaction():
            await set_system_job_scope(claim_connection)
            items = await claim_unapplied_batch_results(
                claim_connection,
                worker_id=worker_id,
                limit=limit,
                lease_seconds=lease_seconds,
            )
    results: list[dict[str, object]] = []
    for item in items:
        handler = handlers.get(item.workload)
        try:
            if handler is None:
                raise ValueError(f"Batch workload Handler가 없습니다: {item.workload}")
            async with pool.connection() as connection:
                async with connection.transaction():
                    applied = await handler(connection, item)
                    await set_system_job_scope(connection)
                    await mark_batch_result_applied(
                        connection,
                        item_id=item.item_id,
                        worker_id=worker_id,
                    )
        except Exception as error:  # noqa: BLE001 - Item별 실패를 격리한다
            async with pool.connection() as connection:
                async with connection.transaction():
                    await set_system_job_scope(connection)
                    await release_batch_result_application(
                        connection,
                        item_id=item.item_id,
                        worker_id=worker_id,
                        error=str(error),
                    )
            results.append(
                {
                    "item_id": item.item_id,
                    "custom_id": item.custom_id,
                    "status": "domain_apply_failed",
                    "error": str(error),
                }
            )
            continue
        results.append(
            {
                "item_id": item.item_id,
                "custom_id": item.custom_id,
                "status": "domain_applied",
                "applied": applied,
            }
        )
    return results


async def run_openai_batch_cycle(
    *,
    database_url: str,
    api_key: str,
    max_items: int = 500,
    max_submissions: int = 1,
    poll_limit: int = 10,
    poll_interval_seconds: int = 60,
    poll_lease_seconds: int = 120,
    worker_id: str = "openai-batch",
    result_apply_limit: int = 100,
    result_apply_lease_seconds: int = 300,
    result_handlers: Mapping[str, ResultHandler] | None = None,
    provider: BatchProvider | None = None,
) -> list[dict[str, object]]:
    """제출과 상태 조회를 한 Cycle 실행하고 외부 호출 중 DB 연결을 반환한다."""
    if not database_url:
        raise ValueError("OpenAI Batch Worker에 database_url이 필요합니다.")
    if max_submissions < 0 or poll_limit < 1:
        raise ValueError("Batch 제출 수는 0 이상, Poll 수는 1 이상이어야 합니다.")
    provider = provider or OpenAIBatchProvider(api_key)
    pool = AsyncConnectionPool(
        conninfo=database_url,
        min_size=1,
        max_size=2,
        kwargs={"row_factory": dict_row},
        open=False,
    )
    await pool.open(wait=True)
    results: list[dict[str, object]] = []
    try:
        for _ in range(max_submissions):
            result = await _submit_batch(
                pool,
                provider=provider,
                max_items=max_items,
                poll_interval_seconds=poll_interval_seconds,
            )
            if result is None:
                break
            results.append(result)
        due_batches = await _claim_due_polls(
            pool,
            limit=poll_limit,
            poll_lease_seconds=poll_lease_seconds,
        )
        for batch in due_batches:
            results.append(
                await _poll_batch(
                    pool,
                    provider=provider,
                    batch=batch,
                    poll_interval_seconds=poll_interval_seconds,
                )
            )
        results.extend(
            await _apply_domain_results(
                pool,
                worker_id=worker_id,
                limit=result_apply_limit,
                lease_seconds=result_apply_lease_seconds,
                handlers=(
                    result_handlers
                    if result_handlers is not None
                    else _default_result_handlers()
                ),
            )
        )
        return results
    finally:
        await pool.close()


async def consume_openai_batches(
    *,
    database_url: str,
    api_key: str,
    interval_seconds: int = 60,
    max_cycles: int | None = None,
    provider_factory: ProviderFactory | None = None,
    on_cycle: CycleObserver | None = None,
    **cycle_kwargs: object,
) -> list[dict[str, object]]:
    """OpenAI Batch Cycle을 설정된 횟수 또는 상주 모드로 반복한다."""
    if interval_seconds < 0 or (max_cycles is not None and max_cycles < 1):
        raise ValueError("Batch 반복 간격은 0 이상이고 횟수는 1 이상이어야 합니다.")
    consumed: list[dict[str, object]] = []
    cycles = 0
    shared_provider = OpenAIBatchProvider(api_key) if provider_factory is None else None
    while max_cycles is None or cycles < max_cycles:
        provider = provider_factory() if provider_factory else shared_provider
        results = await run_openai_batch_cycle(
            database_url=database_url,
            api_key=api_key,
            provider=provider,
            **cycle_kwargs,
        )
        if results and on_cycle is not None:
            on_cycle(results)
        if max_cycles is not None:
            consumed.extend(results)
        cycles += 1
        if max_cycles is None or cycles < max_cycles:
            await asyncio.sleep(interval_seconds)
    return consumed
