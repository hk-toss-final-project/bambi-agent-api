"""LLM Provider 사용량 가격 계산과 PostgreSQL 저장.

호출 계층에서 수집한 시도별 관찰값을 모델 설정의 버전 가격으로 계산하고,
원문 Prompt·응답을 포함하지 않은 운영 이력으로 한 번에 저장한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from agent.llm.api import LlmCallObservation, LlmUsageContext
type DictRow = dict[str, Any]

_MILLION = Decimal("1000000")
_COST_QUANTUM = Decimal("0.000000001")


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """모델 설정 버전에 고정된 Token 단가."""

    model_config_id: str
    provider: str
    model_name: str
    version: int
    input_cost_per_million: Decimal
    cached_input_cost_per_million: Decimal | None
    output_cost_per_million: Decimal
    batch_discount_ratio: Decimal = Decimal("1")
    currency: str = "USD"
    source: str | None = None

    def snapshot(self) -> dict[str, object]:
        """과거 비용을 재현할 수 있는 JSON 가격 Snapshot을 반환한다."""
        return {
            "model_config_id": self.model_config_id,
            "provider": self.provider,
            "model_name": self.model_name,
            "version": self.version,
            "input_cost_per_million": str(self.input_cost_per_million),
            "cached_input_cost_per_million": (
                str(self.cached_input_cost_per_million)
                if self.cached_input_cost_per_million is not None
                else None
            ),
            "output_cost_per_million": str(self.output_cost_per_million),
            "batch_discount_ratio": str(self.batch_discount_ratio),
            "currency": self.currency,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class UsageLogRecord:
    """DB에 저장할 Provider 호출 시도 한 건."""

    feature_id: str
    workload_type: str
    provider: str
    model_name: str | None
    operation: str
    status: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_output_tokens: int = 0
    request_count: int = 1
    latency_ms: int | None = None
    job_id: str | None = None
    generation_run_id: str | None = None
    user_id: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    provider_request_id: str | None = None
    logical_call_id: str = field(default_factory=lambda: str(uuid4()))
    attempt_number: int = 1
    error_code: str | None = None
    http_status: int | None = None
    estimated_cost: Decimal | None = None
    cost_status: str = "unknown"
    cost_currency: str = "USD"
    model_config_id: str | None = None
    pricing_snapshot: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        """음수 Token·시간과 잘못된 호출 시도 번호를 거부한다."""
        token_values = (
            self.input_tokens,
            self.output_tokens,
            self.cached_input_tokens,
            self.reasoning_output_tokens,
        )
        if any(value < 0 for value in token_values):
            raise ValueError("Usage Log Token 수는 0 이상이어야 합니다.")
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("캐시 입력 Token은 전체 입력 Token을 넘을 수 없습니다.")
        if self.request_count < 1 or self.attempt_number < 1:
            raise ValueError("요청 수와 호출 시도 번호는 1 이상이어야 합니다.")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("Usage Log 지연 시간은 0 이상이어야 합니다.")


@dataclass(frozen=True, slots=True)
class UsageSummary:
    """업무·호출 종류·모델별 LLM 사용량 집계."""

    workload_type: str
    operation: str
    provider: str
    model_name: str | None
    call_count: int
    succeeded_count: int
    failed_count: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_output_tokens: int
    estimated_cost: Decimal | None
    unknown_cost_calls: int
    average_latency_ms: Decimal | None
    p95_latency_ms: Decimal | None


def calculate_estimated_cost(
    pricing: ModelPricing,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    operation: str = "chat_completion",
) -> Decimal:
    """호출 Token과 가격 Snapshot으로 예상 USD 비용을 계산한다."""
    if min(input_tokens, output_tokens, cached_input_tokens) < 0:
        raise ValueError("비용 계산 Token 수는 0 이상이어야 합니다.")
    if cached_input_tokens > input_tokens:
        raise ValueError("캐시 입력 Token은 전체 입력 Token을 넘을 수 없습니다.")
    uncached_input_tokens = input_tokens - cached_input_tokens
    cached_rate = (
        pricing.cached_input_cost_per_million
        if pricing.cached_input_cost_per_million is not None
        else pricing.input_cost_per_million
    )
    cost = (
        Decimal(uncached_input_tokens) * pricing.input_cost_per_million
        + Decimal(cached_input_tokens) * cached_rate
        + Decimal(output_tokens) * pricing.output_cost_per_million
    ) / _MILLION
    if operation == "batch_generation":
        cost *= pricing.batch_discount_ratio
    return cost.quantize(_COST_QUANTUM, rounding=ROUND_HALF_UP)


async def load_model_pricing(
    connection: AsyncConnection[DictRow],
    *,
    provider: str,
    model_name: str,
    plan: str | None = None,
    model_config_id: str | None = None,
) -> ModelPricing | None:
    """호출에 사용한 ID 또는 활성 Provider·모델 설정의 최신 가격을 조회한다."""
    cursor = await connection.execute(
        """
        SELECT
            id,
            provider,
            model_name,
            version,
            input_cost_per_million,
            cached_input_cost_per_million,
            output_cost_per_million,
            parameters
        FROM agent.model_configs
        WHERE (
                %s::uuid IS NOT NULL
                AND id = %s::uuid
            )
           OR (
                %s::uuid IS NULL
                AND status = 'active'
                AND provider = %s
                AND model_name = %s
                AND input_cost_per_million IS NOT NULL
                AND output_cost_per_million IS NOT NULL
                AND (plan IS NULL OR plan = %s)
            )
        ORDER BY
            CASE
                WHEN %s::uuid IS NOT NULL THEN 0
                WHEN plan = %s THEN 1
                WHEN plan IS NULL THEN 2
                ELSE 3
            END,
            version DESC
        LIMIT 1
        """,
        (
            model_config_id,
            model_config_id,
            model_config_id,
            provider,
            model_name,
            plan,
            model_config_id,
            plan,
        ),
    )
    row = await cursor.fetchone()
    if (
        row is None
        or row.get("input_cost_per_million") is None
        or row.get("output_cost_per_million") is None
    ):
        return None
    parameters = row.get("parameters")
    config = parameters if isinstance(parameters, Mapping) else {}
    return ModelPricing(
        model_config_id=str(row["id"]),
        provider=str(row["provider"]),
        model_name=str(row["model_name"]),
        version=int(row["version"]),
        input_cost_per_million=Decimal(str(row["input_cost_per_million"])),
        cached_input_cost_per_million=(
            Decimal(str(row["cached_input_cost_per_million"]))
            if row.get("cached_input_cost_per_million") is not None
            else None
        ),
        output_cost_per_million=Decimal(str(row["output_cost_per_million"])),
        batch_discount_ratio=Decimal(str(config.get("batch_discount_ratio") or 1)),
        currency=str(config.get("currency") or "USD"),
        source=str(config.get("pricing_source") or "").strip() or None,
    )


def apply_model_pricing(
    record: UsageLogRecord,
    pricing: ModelPricing | None,
) -> UsageLogRecord:
    """Usage Log에 계산 비용과 불변 가격 Snapshot을 적용한다."""
    if record.status == "cached":
        return replace(
            record,
            estimated_cost=Decimal("0"),
            cost_status="not_applicable",
            pricing_snapshot={},
        )
    if pricing is None:
        return replace(
            record,
            estimated_cost=None,
            cost_status="unknown",
            pricing_snapshot={},
        )
    return replace(
        record,
        model_config_id=pricing.model_config_id,
        estimated_cost=calculate_estimated_cost(
            pricing,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            cached_input_tokens=record.cached_input_tokens,
            operation=record.operation,
        ),
        cost_status="calculated",
        cost_currency=pricing.currency,
        pricing_snapshot=pricing.snapshot(),
    )


def _serialize_usage_record(record: UsageLogRecord) -> dict[str, object]:
    """Usage Log 레코드를 JSONB Batch Insert용 값으로 직렬화한다."""
    return {
        "id": record.id,
        "job_id": record.job_id,
        "generation_run_id": record.generation_run_id,
        "user_id": record.user_id,
        "feature_id": record.feature_id,
        "workload_type": record.workload_type,
        "provider": record.provider,
        "model_name": record.model_name,
        "operation": record.operation,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "cached_input_tokens": record.cached_input_tokens,
        "reasoning_output_tokens": record.reasoning_output_tokens,
        "request_count": record.request_count,
        "estimated_cost": (
            str(record.estimated_cost) if record.estimated_cost is not None else None
        ),
        "latency_ms": record.latency_ms,
        "status": record.status,
        "request_id": record.request_id,
        "trace_id": record.trace_id,
        "provider_request_id": record.provider_request_id,
        "logical_call_id": record.logical_call_id,
        "attempt_number": record.attempt_number,
        "model_config_id": record.model_config_id,
        "error_code": record.error_code,
        "http_status": record.http_status,
        "cost_status": record.cost_status,
        "cost_currency": record.cost_currency,
        "pricing_snapshot": dict(record.pricing_snapshot),
        "metadata": dict(record.metadata),
        "occurred_at": record.occurred_at.isoformat(),
    }


async def insert_usage_logs(
    connection: AsyncConnection[DictRow],
    records: Sequence[UsageLogRecord],
) -> int:
    """호출 시도 목록을 ID 기준 멱등 Batch Insert하고 저장 건수를 반환한다."""
    if not records:
        return 0
    cursor = await connection.execute(
        """
        INSERT INTO agent.usage_logs (
            id,
            job_id,
            generation_run_id,
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
            latency_ms,
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
            item.id::uuid,
            item.job_id::uuid,
            item.generation_run_id::uuid,
            item.user_id,
            item.feature_id,
            item.workload_type,
            item.provider,
            item.model_name,
            item.operation,
            item.input_tokens,
            item.output_tokens,
            item.cached_input_tokens,
            item.reasoning_output_tokens,
            item.request_count,
            item.estimated_cost::numeric,
            item.latency_ms,
            item.status,
            item.request_id,
            item.trace_id,
            item.provider_request_id,
            item.logical_call_id::uuid,
            item.attempt_number,
            item.model_config_id::uuid,
            item.error_code,
            item.http_status,
            item.cost_status,
            item.cost_currency,
            item.pricing_snapshot,
            item.metadata,
            item.occurred_at
        FROM jsonb_to_recordset(%s::jsonb) AS item(
            id text,
            job_id text,
            generation_run_id text,
            user_id text,
            feature_id text,
            workload_type text,
            provider text,
            model_name text,
            operation text,
            input_tokens integer,
            output_tokens integer,
            cached_input_tokens integer,
            reasoning_output_tokens integer,
            request_count integer,
            estimated_cost text,
            latency_ms integer,
            status text,
            request_id text,
            trace_id text,
            provider_request_id text,
            logical_call_id text,
            attempt_number integer,
            model_config_id text,
            error_code text,
            http_status smallint,
            cost_status text,
            cost_currency text,
            pricing_snapshot jsonb,
            metadata jsonb,
            occurred_at timestamptz
        )
        ON CONFLICT (id) DO NOTHING
        RETURNING id
        """,
        (Jsonb([_serialize_usage_record(record) for record in records]),),
    )
    return len(await cursor.fetchall())


async def price_and_insert_usage_logs(
    connection: AsyncConnection[DictRow],
    records: Sequence[UsageLogRecord],
    *,
    plan: str | None = None,
) -> int:
    """모델별 가격을 한 번씩 조회해 계산한 뒤 Usage Log를 일괄 저장한다."""
    pricing_cache: dict[tuple[str, str, str | None], ModelPricing | None] = {}
    priced_records: list[UsageLogRecord] = []
    for record in records:
        if record.status == "cached" or not record.model_name:
            priced_records.append(apply_model_pricing(record, None))
            continue
        key = (record.provider, record.model_name, record.model_config_id)
        if key not in pricing_cache:
            pricing_cache[key] = await load_model_pricing(
                connection,
                provider=record.provider,
                model_name=record.model_name,
                plan=plan,
                model_config_id=record.model_config_id,
            )
        priced_records.append(apply_model_pricing(record, pricing_cache[key]))
    return await insert_usage_logs(connection, priced_records)


async def summarize_usage_logs(
    connection: AsyncConnection[DictRow],
    *,
    started_at: datetime,
    ended_at: datetime,
    workload_type: str | None = None,
    operation: str | None = None,
    user_id: str | None = None,
) -> list[UsageSummary]:
    """기간과 선택 필터로 업무·호출 종류·모델별 사용량을 집계한다."""
    if ended_at <= started_at:
        raise ValueError("사용량 조회 종료 시각은 시작 시각보다 뒤여야 합니다.")
    cursor = await connection.execute(
        """
        SELECT
            workload_type,
            operation,
            provider,
            model_name,
            count(*) AS call_count,
            count(*) FILTER (WHERE status = 'succeeded') AS succeeded_count,
            count(*) FILTER (WHERE status = 'failed') AS failed_count,
            COALESCE(sum(input_tokens), 0) AS input_tokens,
            COALESCE(sum(output_tokens), 0) AS output_tokens,
            COALESCE(sum(cached_input_tokens), 0) AS cached_input_tokens,
            COALESCE(sum(reasoning_output_tokens), 0) AS reasoning_output_tokens,
            sum(estimated_cost) AS estimated_cost,
            count(*) FILTER (WHERE cost_status = 'unknown') AS unknown_cost_calls,
            avg(latency_ms) FILTER (WHERE latency_ms IS NOT NULL)
                AS average_latency_ms,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
                FILTER (WHERE latency_ms IS NOT NULL) AS p95_latency_ms
        FROM agent.usage_logs
        WHERE occurred_at >= %s
          AND occurred_at < %s
          AND (%s::text IS NULL OR workload_type = %s)
          AND (%s::text IS NULL OR operation = %s)
          AND (%s::text IS NULL OR user_id = %s)
        GROUP BY workload_type, operation, provider, model_name
        ORDER BY workload_type, operation, provider, model_name NULLS LAST
        """,
        (
            started_at,
            ended_at,
            workload_type,
            workload_type,
            operation,
            operation,
            user_id,
            user_id,
        ),
    )
    rows = await cursor.fetchall()
    return [
        UsageSummary(
            workload_type=str(row["workload_type"]),
            operation=str(row["operation"]),
            provider=str(row["provider"]),
            model_name=str(row["model_name"]) if row.get("model_name") else None,
            call_count=int(row["call_count"]),
            succeeded_count=int(row["succeeded_count"]),
            failed_count=int(row["failed_count"]),
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            cached_input_tokens=int(row["cached_input_tokens"]),
            reasoning_output_tokens=int(row["reasoning_output_tokens"]),
            estimated_cost=(
                Decimal(str(row["estimated_cost"]))
                if row.get("estimated_cost") is not None
                else None
            ),
            unknown_cost_calls=int(row["unknown_cost_calls"]),
            average_latency_ms=(
                Decimal(str(row["average_latency_ms"]))
                if row.get("average_latency_ms") is not None
                else None
            ),
            p95_latency_ms=(
                Decimal(str(row["p95_latency_ms"]))
                if row.get("p95_latency_ms") is not None
                else None
            ),
        )
        for row in rows
    ]


def usage_log_records_from_observations(
    observations: Sequence[LlmCallObservation],
    *,
    context: LlmUsageContext,
) -> list[UsageLogRecord]:
    """호출 관찰값에 실행 귀속 Context를 결합해 DB 저장 레코드로 변환한다."""
    records: list[UsageLogRecord] = []
    for observation in observations:
        records.append(
            UsageLogRecord(
                feature_id=context.feature_id,
                workload_type=context.workload_type,
                provider=observation.provider,
                model_name=observation.model,
                operation=observation.operation,
                status=observation.status,
                input_tokens=observation.input_tokens,
                output_tokens=observation.output_tokens,
                cached_input_tokens=observation.cached_input_tokens,
                reasoning_output_tokens=observation.reasoning_output_tokens,
                latency_ms=observation.latency_ms,
                job_id=context.job_id,
                generation_run_id=context.generation_run_id,
                user_id=context.user_id,
                request_id=context.request_id,
                trace_id=context.trace_id,
                provider_request_id=observation.request_id,
                logical_call_id=observation.logical_call_id,
                attempt_number=observation.attempt_number,
                error_code=observation.error_code,
                http_status=observation.http_status,
                metadata={**dict(context.metadata), **observation.metadata},
                occurred_at=observation.occurred_at,
            )
        )
    return records
