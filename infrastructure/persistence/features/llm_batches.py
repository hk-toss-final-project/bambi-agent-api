"""OpenAI Batch와 custom_id별 Item을 PostgreSQL에 저장하는 기능.

외부 API 호출 전후의 짧은 상태 변경만 담당한다. JSONL 업로드·상태 조회 중에는
이 모듈의 Transaction이나 Row Lock을 유지하지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from shared.openai_batch import ProviderBatchSnapshot

type DictRow = dict[str, Any]

_ACTIVE_PROVIDER_STATUSES = {
    "submitted",
    "validating",
    "in_progress",
    "finalizing",
    "cancelling",
}
_TERMINAL_PROVIDER_STATUSES = {"completed", "failed", "expired", "cancelled"}


@dataclass(frozen=True, slots=True)
class EnqueueLlmBatchItemCommand:
    """OpenAI Batch Item을 멱등 등록하는 명령."""

    user_id: str
    custom_id: str
    endpoint: str
    model_name: str
    workload: str
    resource_type: str
    resource_id: str
    request_body: Mapping[str, object]
    context: Mapping[str, object] = field(default_factory=dict)
    job_id: str | None = None
    provider: str = "openai"
    max_attempts: int = 3


@dataclass(frozen=True, slots=True)
class StoredLlmBatchItem:
    """저장된 Batch Item의 식별자와 현재 상태."""

    item_id: str
    custom_id: str
    status: str
    batch_id: str | None


@dataclass(frozen=True, slots=True)
class PreparedLlmBatchItem:
    """JSONL 입력으로 만들기 위해 점유한 Item."""

    item_id: str
    custom_id: str
    request_body: dict[str, object]


@dataclass(frozen=True, slots=True)
class PreparedLlmBatch:
    """같은 endpoint·model·workload로 묶인 로컬 제출 Batch."""

    batch_id: str
    provider: str
    endpoint: str
    model_name: str
    workload: str
    items: tuple[PreparedLlmBatchItem, ...]


@dataclass(frozen=True, slots=True)
class DueLlmBatch:
    """Provider 상태를 다시 조회할 시각이 된 Batch."""

    batch_id: str
    provider_batch_id: str
    endpoint: str
    model_name: str
    workload: str


@dataclass(frozen=True, slots=True)
class ClaimedBatchResultItem:
    """도메인 반영을 위해 Lease로 점유한 완료 Item."""

    item_id: str
    custom_id: str
    user_id: str
    job_id: str | None
    workload: str
    model_name: str
    resource_type: str
    resource_id: str
    context: dict[str, object]
    result_body: dict[str, object]


async def enqueue_llm_batch_item(
    connection: AsyncConnection[DictRow],
    command: EnqueueLlmBatchItemCommand,
) -> StoredLlmBatchItem:
    """custom_id가 같은 요청을 중복 생성하지 않고 Batch Item을 등록한다."""
    if not command.user_id or not command.custom_id:
        raise ValueError("Batch Item의 user_id와 custom_id가 필요합니다.")
    if not command.model_name or not command.workload:
        raise ValueError("Batch Item의 model_name과 workload가 필요합니다.")
    if command.max_attempts < 1:
        raise ValueError("Batch Item의 max_attempts는 1 이상이어야 합니다.")
    cursor = await connection.execute(
        """
        INSERT INTO agent.llm_batch_items (
            job_id, user_id, custom_id, provider, endpoint, model_name, workload,
            resource_type, resource_id, request_body, context, max_attempts
        ) VALUES (
            %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (custom_id) DO NOTHING
        RETURNING id::text AS item_id, custom_id, status, batch_id::text
        """,
        (
            command.job_id,
            command.user_id,
            command.custom_id,
            command.provider,
            command.endpoint,
            command.model_name,
            command.workload,
            command.resource_type,
            command.resource_id,
            Jsonb(dict(command.request_body)),
            Jsonb(dict(command.context)),
            command.max_attempts,
        ),
    )
    row = await cursor.fetchone()
    if row is None:
        cursor = await connection.execute(
            """
            SELECT id::text AS item_id, custom_id, status, batch_id::text
            FROM agent.llm_batch_items
            WHERE custom_id = %s
            """,
            (command.custom_id,),
        )
        row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("OpenAI Batch Item을 등록하거나 조회하지 못했습니다.")
    return StoredLlmBatchItem(
        item_id=str(row["item_id"]),
        custom_id=str(row["custom_id"]),
        status=str(row["status"]),
        batch_id=str(row["batch_id"]) if row.get("batch_id") else None,
    )


async def claim_llm_batch(
    connection: AsyncConnection[DictRow],
    *,
    max_items: int = 500,
) -> PreparedLlmBatch | None:
    """같은 Provider·endpoint·model·workload의 대기 Item을 제출 Batch로 점유한다."""
    if max_items < 1 or max_items > 50_000:
        raise ValueError("OpenAI Batch Item 수는 1~50000이어야 합니다.")
    cursor = await connection.execute(
        """
        SELECT provider, endpoint, model_name, workload
        FROM agent.llm_batch_items
        WHERE status = 'queued' AND attempt_count < max_attempts
        ORDER BY created_at, id
        FOR UPDATE SKIP LOCKED
        LIMIT 1
        """
    )
    group = await cursor.fetchone()
    if group is None:
        return None
    cursor = await connection.execute(
        """
        SELECT id::text AS item_id, custom_id, request_body
        FROM agent.llm_batch_items
        WHERE status = 'queued'
          AND attempt_count < max_attempts
          AND provider = %s
          AND endpoint = %s
          AND model_name = %s
          AND workload = %s
        ORDER BY created_at, id
        FOR UPDATE SKIP LOCKED
        LIMIT %s
        """,
        (
            group["provider"],
            group["endpoint"],
            group["model_name"],
            group["workload"],
            max_items,
        ),
    )
    rows = await cursor.fetchall()
    if not rows:
        return None
    cursor = await connection.execute(
        """
        INSERT INTO agent.llm_batches (
            provider, endpoint, model_name, workload, item_count
        ) VALUES (%s, %s, %s, %s, %s)
        RETURNING id::text AS batch_id
        """,
        (
            group["provider"],
            group["endpoint"],
            group["model_name"],
            group["workload"],
            len(rows),
        ),
    )
    batch_row = await cursor.fetchone()
    if batch_row is None:
        raise RuntimeError("로컬 OpenAI Batch를 생성하지 못했습니다.")
    batch_id = str(batch_row["batch_id"])
    item_ids = [str(row["item_id"]) for row in rows]
    await connection.execute(
        """
        UPDATE agent.llm_batch_items
        SET batch_id = %s::uuid, status = 'preparing'
        WHERE id = ANY(%s::uuid[])
        """,
        (batch_id, item_ids),
    )
    return PreparedLlmBatch(
        batch_id=batch_id,
        provider=str(group["provider"]),
        endpoint=str(group["endpoint"]),
        model_name=str(group["model_name"]),
        workload=str(group["workload"]),
        items=tuple(
            PreparedLlmBatchItem(
                item_id=str(row["item_id"]),
                custom_id=str(row["custom_id"]),
                request_body=dict(row["request_body"]),
            )
            for row in rows
        ),
    )


async def mark_llm_batch_submitted(
    connection: AsyncConnection[DictRow],
    *,
    batch_id: str,
    provider_batch_id: str,
    input_file_id: str,
    initial_status: str,
    poll_after_seconds: int,
) -> None:
    """외부 제출 식별자와 최초 상태를 저장하고 Item을 submitted로 전환한다."""
    if initial_status not in _ACTIVE_PROVIDER_STATUSES | _TERMINAL_PROVIDER_STATUSES:
        raise ValueError("지원하지 않는 OpenAI Batch 상태입니다.")
    stored_status = (
        initial_status if initial_status in _ACTIVE_PROVIDER_STATUSES else "submitted"
    )
    await connection.execute(
        """
        UPDATE agent.llm_batches
        SET status = %s,
            provider_batch_id = %s,
            input_file_id = %s,
            submitted_at = clock_timestamp(),
            next_poll_at = clock_timestamp() + (%s * interval '1 second')
        WHERE id = %s::uuid AND status = 'preparing'
        """,
        (stored_status, provider_batch_id, input_file_id, poll_after_seconds, batch_id),
    )
    await connection.execute(
        """
        UPDATE agent.llm_batch_items
        SET status = 'submitted', attempt_count = attempt_count + 1
        WHERE batch_id = %s::uuid AND status = 'preparing'
        """,
        (batch_id,),
    )


async def release_failed_llm_batch_submission(
    connection: AsyncConnection[DictRow],
    *,
    batch_id: str,
    error: str,
) -> None:
    """제출 실패 Batch를 기록하고 재시도 가능한 Item만 대기열로 돌린다."""
    await connection.execute(
        """
        UPDATE agent.llm_batches
        SET status = 'failed', provider_errors = %s, completed_at = clock_timestamp()
        WHERE id = %s::uuid AND status = 'preparing'
        """,
        (Jsonb([{"message": error[:2000]}]), batch_id),
    )
    await connection.execute(
        """
        UPDATE agent.llm_batch_items
        SET batch_id = NULL,
            attempt_count = attempt_count + 1,
            status = CASE
                WHEN attempt_count + 1 < max_attempts THEN 'queued'
                ELSE 'failed'
            END,
            error = %s
        WHERE batch_id = %s::uuid AND status = 'preparing'
        """,
        (Jsonb({"type": "submission_error", "message": error[:2000]}), batch_id),
    )


async def claim_due_llm_batches(
    connection: AsyncConnection[DictRow],
    *,
    limit: int,
    poll_lease_seconds: int,
) -> list[DueLlmBatch]:
    """조회 시각이 된 Batch를 짧은 Poll Lease로 점유한다."""
    if limit < 1 or poll_lease_seconds < 1:
        raise ValueError("Batch Poll limit과 Lease는 1 이상이어야 합니다.")
    cursor = await connection.execute(
        """
        WITH candidates AS (
            SELECT id
            FROM agent.llm_batches
            WHERE status IN (
                'submitted', 'validating', 'in_progress', 'finalizing', 'cancelling'
            )
              AND next_poll_at <= clock_timestamp()
            ORDER BY next_poll_at, created_at
            FOR UPDATE SKIP LOCKED
            LIMIT %s
        )
        UPDATE agent.llm_batches AS batch
        SET next_poll_at = clock_timestamp() + (%s * interval '1 second'),
            poll_attempt_count = poll_attempt_count + 1
        FROM candidates
        WHERE batch.id = candidates.id
        RETURNING batch.id::text AS batch_id,
                  batch.provider_batch_id,
                  batch.endpoint,
                  batch.model_name,
                  batch.workload
        """,
        (limit, poll_lease_seconds),
    )
    return [
        DueLlmBatch(
            batch_id=str(row["batch_id"]),
            provider_batch_id=str(row["provider_batch_id"]),
            endpoint=str(row["endpoint"]),
            model_name=str(row["model_name"]),
            workload=str(row["workload"]),
        )
        for row in await cursor.fetchall()
    ]


async def update_llm_batch_snapshot(
    connection: AsyncConnection[DictRow],
    *,
    batch_id: str,
    snapshot: ProviderBatchSnapshot,
    poll_after_seconds: int,
) -> None:
    """Provider Batch 상태·파일·오류를 저장하고 다음 Poll 시각을 정한다."""
    if snapshot.status not in _ACTIVE_PROVIDER_STATUSES | _TERMINAL_PROVIDER_STATUSES:
        raise ValueError("지원하지 않는 OpenAI Batch 상태입니다.")
    terminal = snapshot.status in _TERMINAL_PROVIDER_STATUSES
    await connection.execute(
        """
        UPDATE agent.llm_batches
        SET status = %s,
            input_file_id = COALESCE(%s, input_file_id),
            output_file_id = COALESCE(%s, output_file_id),
            error_file_id = COALESCE(%s, error_file_id),
            provider_errors = %s,
            metadata = metadata || %s,
            next_poll_at = CASE
                WHEN %s THEN NULL
                ELSE clock_timestamp() + (%s * interval '1 second')
            END,
            completed_at = CASE WHEN %s THEN clock_timestamp() ELSE NULL END
        WHERE id = %s::uuid
        """,
        (
            snapshot.status,
            snapshot.input_file_id,
            snapshot.output_file_id,
            snapshot.error_file_id,
            Jsonb(snapshot.errors or []),
            Jsonb(dict(snapshot.metadata)),
            terminal,
            poll_after_seconds,
            terminal,
            batch_id,
        ),
    )


def _result_usage(
    body: Mapping[str, object],
) -> tuple[int | None, int | None, int | None, int | None]:
    """Batch 결과에서 입력·출력·캐시·Reasoning Token을 추출한다."""
    usage = body.get("usage")
    if not isinstance(usage, Mapping):
        return None, None, None, None
    input_value = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_value = usage.get("output_tokens", usage.get("completion_tokens"))
    input_tokens = int(input_value) if isinstance(input_value, int) else None
    output_tokens = int(output_value) if isinstance(output_value, int) else None
    input_details = usage.get("input_tokens_details", usage.get("prompt_tokens_details"))
    output_details = usage.get(
        "output_tokens_details",
        usage.get("completion_tokens_details"),
    )
    cached_value = (
        input_details.get("cached_tokens")
        if isinstance(input_details, Mapping)
        else None
    )
    reasoning_value = (
        output_details.get("reasoning_tokens")
        if isinstance(output_details, Mapping)
        else None
    )
    cached_tokens = int(cached_value) if isinstance(cached_value, int) else None
    reasoning_tokens = (
        int(reasoning_value) if isinstance(reasoning_value, int) else None
    )
    return input_tokens, output_tokens, cached_tokens, reasoning_tokens


async def _insert_batch_usage_logs(
    connection: AsyncConnection[DictRow],
    *,
    batch_id: str,
    custom_ids: Sequence[str],
) -> None:
    """반영된 Batch Item 시도를 가격 Snapshot과 함께 멱등 Usage Log로 저장한다."""
    if not custom_ids:
        return
    await connection.execute(
        """
        INSERT INTO agent.usage_logs (
            id,
            job_id,
            user_id,
            feature_id,
            workload_type,
            provider,
            model_name,
            operation,
            input_tokens,
            output_tokens,
            cached_input_tokens,
            reasoning_output_tokens,
            request_count,
            estimated_cost,
            status,
            request_id,
            trace_id,
            provider_request_id,
            logical_call_id,
            attempt_number,
            model_config_id,
            error_code,
            http_status,
            cost_status,
            cost_currency,
            pricing_snapshot,
            metadata,
            occurred_at
        )
        SELECT
            md5(item.id::text || ':' || item.attempt_count::text)::uuid,
            item.job_id,
            item.user_id,
            COALESCE(job.feature_id, 'LLM-015'),
            CASE
                WHEN item.workload = 'report_generation'
                     AND (
                        COALESCE(job.payload->>'generation_scope', '') = 'WIKI_BRIEFING'
                        OR COALESCE(job.payload->>'report_type', '') = 'MORNING_BRIEFING'
                     ) THEN 'report_morning'
                WHEN item.workload = 'report_generation' THEN 'report_on_demand'
                WHEN item.workload = 'wiki_embedding'
                     AND (
                        job.feature_id = 'WBA-002'
                        OR COALESCE(job.payload->>'trigger', '') = 'maintenance'
                     ) THEN 'wiki_maintenance'
                WHEN item.workload = 'wiki_embedding' THEN 'wiki_build'
                ELSE 'other'
            END,
            item.provider,
            item.model_name,
            CASE
                WHEN item.endpoint = '/v1/embeddings' THEN 'embedding'
                ELSE 'batch_generation'
            END,
            COALESCE(item.input_tokens, 0)::integer,
            COALESCE(item.output_tokens, 0)::integer,
            LEAST(
                COALESCE(item.cached_input_tokens, 0),
                COALESCE(item.input_tokens, 0)
            )::integer,
            LEAST(
                COALESCE(item.reasoning_output_tokens, 0),
                COALESCE(item.output_tokens, 0)
            )::integer,
            1,
            CASE
                WHEN pricing.id IS NULL THEN NULL
                ELSE round(
                    (
                        (
                            COALESCE(item.input_tokens, 0)
                            - LEAST(
                                COALESCE(item.cached_input_tokens, 0),
                                COALESCE(item.input_tokens, 0)
                            )
                        ) * pricing.input_cost_per_million
                        + LEAST(
                            COALESCE(item.cached_input_tokens, 0),
                            COALESCE(item.input_tokens, 0)
                        ) * COALESCE(
                            pricing.cached_input_cost_per_million,
                            pricing.input_cost_per_million
                        )
                        + COALESCE(item.output_tokens, 0)
                            * pricing.output_cost_per_million
                    ) / 1000000.0
                    * COALESCE(
                        (pricing.parameters->>'batch_discount_ratio')::numeric,
                        1
                    ),
                    9
                )
            END,
            CASE WHEN item.status = 'completed' THEN 'succeeded' ELSE 'failed' END,
            job.request_id,
            job.trace_id,
            item.provider_request_id,
            item.id,
            GREATEST(item.attempt_count, 1),
            pricing.id,
            COALESCE(item.error->>'code', item.error->>'type'),
            item.response_status_code,
            CASE WHEN pricing.id IS NULL THEN 'unknown' ELSE 'calculated' END,
            'USD',
            CASE
                WHEN pricing.id IS NULL THEN '{}'::jsonb
                ELSE jsonb_build_object(
                    'model_config_id', pricing.id,
                    'provider', pricing.provider,
                    'model_name', pricing.model_name,
                    'version', pricing.version,
                    'input_cost_per_million', pricing.input_cost_per_million,
                    'cached_input_cost_per_million',
                        pricing.cached_input_cost_per_million,
                    'output_cost_per_million', pricing.output_cost_per_million,
                    'batch_discount_ratio', COALESCE(
                        (pricing.parameters->>'batch_discount_ratio')::numeric,
                        1
                    ),
                    'currency', 'USD',
                    'source', pricing.parameters->>'pricing_source'
                )
            END,
            jsonb_build_object(
                'batch_id', item.batch_id,
                'custom_id', item.custom_id,
                'batch_workload', item.workload,
                'endpoint', item.endpoint,
                'execution_mode', 'batch'
            ),
            COALESCE(batch.completed_at, item.updated_at)
        FROM agent.llm_batch_items AS item
        JOIN agent.llm_batches AS batch ON batch.id = item.batch_id
        LEFT JOIN agent.agent_jobs AS job ON job.id = item.job_id
        LEFT JOIN LATERAL (
            SELECT config.*
            FROM agent.model_configs AS config
            WHERE config.status = 'active'
              AND config.provider = item.provider
              AND config.model_name = item.model_name
              AND config.plan IS NULL
              AND config.input_cost_per_million IS NOT NULL
              AND config.output_cost_per_million IS NOT NULL
            ORDER BY config.version DESC
            LIMIT 1
        ) AS pricing ON true
        WHERE item.batch_id = %s::uuid
          AND item.custom_id = ANY(%s::text[])
          AND item.status IN ('completed', 'failed')
        ON CONFLICT (id) DO NOTHING
        """,
        (batch_id, list(custom_ids)),
    )


async def apply_llm_batch_result_lines(
    connection: AsyncConnection[DictRow],
    *,
    batch_id: str,
    lines: Sequence[Mapping[str, object]],
    terminal_status: str,
) -> dict[str, int]:
    """순서가 섞인 output·error 줄을 custom_id로 찾아 Item 결과에 멱등 반영한다."""
    seen: set[str] = set()
    applied_custom_ids: list[str] = []
    completed = 0
    failed = 0
    for line in lines:
        custom_id = str(line.get("custom_id") or "").strip()
        if not custom_id or custom_id in seen:
            continue
        seen.add(custom_id)
        applied_custom_ids.append(custom_id)
        response = line.get("response")
        error = line.get("error")
        response_map = response if isinstance(response, Mapping) else {}
        body = response_map.get("body")
        result_body = dict(body) if isinstance(body, Mapping) else None
        raw_status = response_map.get("status_code")
        status_code = int(raw_status) if isinstance(raw_status, int) else None
        succeeded = (
            error is None
            and result_body is not None
            and status_code is not None
            and 200 <= status_code < 300
        )
        (
            input_tokens,
            output_tokens,
            cached_input_tokens,
            reasoning_output_tokens,
        ) = _result_usage(result_body or {})
        cursor = await connection.execute(
            """
            UPDATE agent.llm_batch_items
            SET status = %s,
                provider_request_id = %s,
                response_status_code = %s,
                result_body = %s,
                error = %s,
                input_tokens = %s,
                output_tokens = %s,
                cached_input_tokens = %s,
                reasoning_output_tokens = %s
            WHERE batch_id = %s::uuid
              AND custom_id = %s
              AND status = 'submitted'
            RETURNING id
            """,
            (
                "completed" if succeeded else "failed",
                response_map.get("request_id"),
                status_code,
                Jsonb(result_body) if result_body is not None else None,
                Jsonb(error) if error is not None else None,
                input_tokens,
                output_tokens,
                cached_input_tokens,
                reasoning_output_tokens,
                batch_id,
                custom_id,
            ),
        )
        if await cursor.fetchone() is None:
            raise ValueError(
                f"Batch {batch_id}에 속하지 않은 custom_id 결과입니다: {custom_id}"
            )
        if succeeded:
            completed += 1
        else:
            failed += 1
    await _insert_batch_usage_logs(
        connection,
        batch_id=batch_id,
        custom_ids=applied_custom_ids,
    )
    requeue = terminal_status in {"failed", "expired", "cancelled"}
    cursor = await connection.execute(
        """
        UPDATE agent.llm_batch_items
        SET batch_id = CASE WHEN %s THEN NULL ELSE batch_id END,
            status = CASE
                WHEN %s AND attempt_count < max_attempts THEN 'queued'
                ELSE 'failed'
            END,
            error = COALESCE(
                error,
                jsonb_build_object('type', 'missing_batch_result', 'batch_status', %s)
            )
        WHERE batch_id = %s::uuid AND status = 'submitted'
        RETURNING status
        """,
        (requeue, requeue, terminal_status, batch_id),
    )
    unresolved = await cursor.fetchall()
    return {
        "completed": completed,
        "failed": failed + sum(row["status"] == "failed" for row in unresolved),
        "requeued": sum(row["status"] == "queued" for row in unresolved),
    }


async def claim_unapplied_batch_results(
    connection: AsyncConnection[DictRow],
    *,
    worker_id: str,
    limit: int,
    lease_seconds: int,
) -> list[ClaimedBatchResultItem]:
    """완료됐지만 도메인에 반영되지 않은 Item을 Lease로 점유한다."""
    if not worker_id or limit < 1 or lease_seconds < 1:
        raise ValueError("결과 반영 Worker ID, limit과 Lease가 필요합니다.")
    cursor = await connection.execute(
        """
        WITH candidates AS (
            SELECT id
            FROM agent.llm_batch_items
            WHERE status = 'completed'
              AND domain_applied_at IS NULL
              AND (
                  domain_apply_claimed_at IS NULL
                  OR domain_apply_claimed_at < clock_timestamp()
                     - (%s * interval '1 second')
              )
            ORDER BY updated_at, id
            FOR UPDATE SKIP LOCKED
            LIMIT %s
        )
        UPDATE agent.llm_batch_items AS item
        SET domain_apply_worker_id = %s,
            domain_apply_claimed_at = clock_timestamp(),
            domain_apply_error = NULL
        FROM candidates
        WHERE item.id = candidates.id
        RETURNING item.id::text AS item_id,
                  item.custom_id,
                  item.user_id,
                  item.job_id::text,
                  item.workload,
                  item.model_name,
                  item.resource_type,
                  item.resource_id,
                  item.context,
                  item.result_body
        """,
        (lease_seconds, limit, worker_id),
    )
    return [
        ClaimedBatchResultItem(
            item_id=str(row["item_id"]),
            custom_id=str(row["custom_id"]),
            user_id=str(row["user_id"]),
            job_id=str(row["job_id"]) if row.get("job_id") else None,
            workload=str(row["workload"]),
            model_name=str(row["model_name"]),
            resource_type=str(row["resource_type"]),
            resource_id=str(row["resource_id"]),
            context=dict(row["context"]),
            result_body=dict(row["result_body"]),
        )
        for row in await cursor.fetchall()
    ]


async def mark_batch_result_applied(
    connection: AsyncConnection[DictRow],
    *,
    item_id: str,
    worker_id: str,
) -> None:
    """도메인 반영을 마친 Item을 소유권 검증 후 완료 처리한다."""
    cursor = await connection.execute(
        """
        UPDATE agent.llm_batch_items
        SET domain_applied_at = clock_timestamp(), domain_apply_error = NULL
        WHERE id = %s::uuid
          AND domain_apply_worker_id = %s
          AND domain_applied_at IS NULL
        RETURNING id
        """,
        (item_id, worker_id),
    )
    if await cursor.fetchone() is None:
        raise RuntimeError("Batch 결과 반영 Lease 소유권이 없습니다.")


async def release_batch_result_application(
    connection: AsyncConnection[DictRow],
    *,
    item_id: str,
    worker_id: str,
    error: str,
) -> None:
    """도메인 반영 실패를 기록하고 Item Lease를 즉시 해제한다."""
    await connection.execute(
        """
        UPDATE agent.llm_batch_items
        SET domain_apply_worker_id = NULL,
            domain_apply_claimed_at = NULL,
            domain_apply_error = %s
        WHERE id = %s::uuid
          AND domain_apply_worker_id = %s
          AND domain_applied_at IS NULL
        """,
        (error[:2000], item_id, worker_id),
    )
