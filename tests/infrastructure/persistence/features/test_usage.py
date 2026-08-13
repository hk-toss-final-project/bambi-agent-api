"""LLM 사용량 가격 계산과 Batch 저장을 검증한다."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from agent.llm.api import LlmCallObservation, LlmUsageContext
from infrastructure.persistence.api import (
    ModelPricing,
    UsageLogRecord,
    apply_model_pricing,
    calculate_estimated_cost,
    price_and_insert_usage_logs,
    summarize_usage_logs,
    usage_log_records_from_observations,
)


class _FakeCursor:
    """가격 조회와 INSERT 결과를 반환하는 테스트 Cursor."""

    def __init__(
        self,
        *,
        row: dict[str, Any] | None = None,
        rows: list[dict[str, Any]] | None = None,
    ) -> None:
        """단건 또는 복수 반환값을 보관한다."""
        self.row = row
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        """설정한 단건 Row를 반환한다."""
        return self.row

    async def fetchall(self) -> list[dict[str, Any]]:
        """설정한 복수 Row를 반환한다."""
        return self.rows


class _FakeConnection:
    """가격 SELECT와 Usage Log INSERT를 기록하는 테스트 Connection."""

    def __init__(self, pricing_row: dict[str, Any] | None) -> None:
        """조회에서 반환할 모델 가격 Row를 보관한다."""
        self.pricing_row = pricing_row
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    async def execute(
        self,
        query: str,
        params: tuple[object, ...],
    ) -> _FakeCursor:
        """SQL과 인자를 기록하고 SQL 종류에 맞는 Cursor를 반환한다."""
        self.executed.append((query, params))
        if "FROM agent.model_configs" in query:
            return _FakeCursor(row=self.pricing_row)
        payload = params[0].obj  # type: ignore[attr-defined]
        return _FakeCursor(rows=[{"id": item["id"]} for item in payload])


class _SummaryConnection:
    """사용량 집계 결과와 실행 인자를 기록하는 테스트 Connection."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        """집계 조회가 반환할 Row를 보관한다."""
        self.rows = rows
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    async def execute(
        self,
        query: str,
        params: tuple[object, ...],
    ) -> _FakeCursor:
        """집계 SQL과 인자를 기록하고 준비한 Row를 반환한다."""
        self.executed.append((query, params))
        return _FakeCursor(rows=self.rows)


def _pricing() -> ModelPricing:
    """테스트용 GPT-4.1 mini 가격을 반환한다."""
    return ModelPricing(
        model_config_id="00000000-0000-0000-0000-000000000011",
        provider="openai",
        model_name="gpt-4.1-mini",
        version=1,
        input_cost_per_million=Decimal("0.4"),
        cached_input_cost_per_million=Decimal("0.1"),
        output_cost_per_million=Decimal("1.6"),
        batch_discount_ratio=Decimal("0.5"),
        source="https://openai.com/index/gpt-4-1/",
    )


def _pricing_row() -> dict[str, object]:
    """DB 조회 결과 형태의 GPT-4.1 mini 가격 Row를 반환한다."""
    return {
        "id": "00000000-0000-0000-0000-000000000011",
        "provider": "openai",
        "model_name": "gpt-4.1-mini",
        "version": 1,
        "input_cost_per_million": Decimal("0.4"),
        "cached_input_cost_per_million": Decimal("0.1"),
        "output_cost_per_million": Decimal("1.6"),
        "parameters": {
            "batch_discount_ratio": 0.5,
            "pricing_source": "https://openai.com/index/gpt-4-1/",
        },
    }


def test_calculate_estimated_cost_separates_cached_input() -> None:
    """캐시 입력 Token은 별도 할인 단가로 계산한다."""
    cost = calculate_estimated_cost(
        _pricing(),
        input_tokens=1_000_000,
        cached_input_tokens=250_000,
        output_tokens=100_000,
    )

    assert cost == Decimal("0.485000000")


def test_calculate_estimated_cost_applies_batch_discount() -> None:
    """Batch 생성은 모델 설정의 할인율을 최종 비용에 적용한다."""
    cost = calculate_estimated_cost(
        _pricing(),
        input_tokens=1_000_000,
        output_tokens=100_000,
        operation="batch_generation",
    )

    assert cost == Decimal("0.280000000")


def test_apply_model_pricing_marks_unknown_and_cached_costs() -> None:
    """가격 미등록 호출과 내부 캐시 적중의 비용 상태를 구분한다."""
    unknown = UsageLogRecord(
        feature_id="REPORT-008",
        workload_type="report_on_demand",
        provider="openai",
        model_name="unknown-model",
        operation="chat_completion",
        status="succeeded",
    )
    cached = UsageLogRecord(
        feature_id="REPORT-008",
        workload_type="report_on_demand",
        provider="internal",
        model_name=None,
        operation="cached",
        status="cached",
    )

    assert apply_model_pricing(unknown, None).cost_status == "unknown"
    priced_cached = apply_model_pricing(cached, None)
    assert priced_cached.cost_status == "not_applicable"
    assert priced_cached.estimated_cost == Decimal("0")


def test_price_and_insert_usage_logs_reuses_model_lookup_and_batches_rows() -> None:
    """같은 모델 가격은 한 번 조회하고 여러 호출을 한 INSERT로 저장한다."""
    connection = _FakeConnection(_pricing_row())
    records = [
        UsageLogRecord(
            feature_id="REPORT-008",
            workload_type="report_on_demand",
            provider="openai",
            model_name="gpt-4.1-mini",
            operation="chat_completion",
            status="succeeded",
            input_tokens=100,
            output_tokens=20,
            metadata={"finish_reason": "stop"},
        ),
        UsageLogRecord(
            feature_id="REPORT-008",
            workload_type="report_on_demand",
            provider="openai",
            model_name="gpt-4.1-mini",
            operation="tool_completion",
            status="failed",
            latency_ms=35,
            error_code="rate_limit_exceeded",
        ),
    ]

    inserted = asyncio.run(
        price_and_insert_usage_logs(  # type: ignore[arg-type]
            connection,
            records,
        )
    )

    assert inserted == 2
    assert len(connection.executed) == 2
    pricing_query = connection.executed[0][0]
    assert "input_cost_per_million IS NOT NULL" in pricing_query
    assert "output_cost_per_million IS NOT NULL" in pricing_query
    insert_payload = connection.executed[1][1][0].obj  # type: ignore[attr-defined]
    assert [item["cost_status"] for item in insert_payload] == [
        "calculated",
        "calculated",
    ]
    assert insert_payload[0]["pricing_snapshot"]["version"] == 1
    assert "prompt" not in insert_payload[0]["metadata"]
    assert "response" not in insert_payload[0]["metadata"]


def test_price_and_insert_usage_logs_keeps_missing_rates_unknown() -> None:
    """모델 설정은 있어도 필수 단가가 없으면 비용을 0원으로 만들지 않는다."""
    pricing_row = _pricing_row()
    pricing_row["input_cost_per_million"] = None
    connection = _FakeConnection(pricing_row)
    record = UsageLogRecord(
        feature_id="REPORT-008",
        workload_type="report_on_demand",
        provider="openai",
        model_name="gpt-4.1-mini",
        operation="chat_completion",
        status="succeeded",
        input_tokens=100,
    )

    inserted = asyncio.run(
        price_and_insert_usage_logs(  # type: ignore[arg-type]
            connection,
            [record],
        )
    )

    assert inserted == 1
    insert_payload = connection.executed[1][1][0].obj  # type: ignore[attr-defined]
    assert insert_payload[0]["estimated_cost"] is None
    assert insert_payload[0]["cost_status"] == "unknown"


def test_usage_log_records_combine_observation_with_job_context() -> None:
    """호출 관찰값에 Job 업무·사용자·추적 Context를 정확히 결합한다."""
    observation = LlmCallObservation(
        model="gpt-4o-mini",
        input_tokens=120,
        output_tokens=30,
        cached_input_tokens=40,
        reasoning_output_tokens=5,
        request_id="provider-req",
        operation="tool_completion",
        status="succeeded",
        latency_ms=250,
        logical_call_id="00000000-0000-0000-0000-000000000021",
        attempt_number=2,
        metadata={"finish_reason": "stop"},
    )
    context = LlmUsageContext(
        feature_id="SVC-008",
        workload_type="report_morning",
        user_id="user-1",
        job_id="00000000-0000-0000-0000-000000000022",
        request_id="internal-req",
        trace_id="trace-1",
        metadata={"report_type": "MORNING_BRIEFING"},
    )

    records = usage_log_records_from_observations([observation], context=context)

    assert len(records) == 1
    record = records[0]
    assert record.feature_id == "SVC-008"
    assert record.workload_type == "report_morning"
    assert record.operation == "tool_completion"
    assert record.provider_request_id == "provider-req"
    assert record.request_id == "internal-req"
    assert record.trace_id == "trace-1"
    assert record.cached_input_tokens == 40
    assert record.metadata == {
        "report_type": "MORNING_BRIEFING",
        "finish_reason": "stop",
    }


def test_summarize_usage_logs_groups_workload_operation_and_model() -> None:
    """업무·호출 종류·모델별 Token·비용·지연시간 집계를 반환한다."""
    connection = _SummaryConnection(
        [
            {
                "workload_type": "report_morning",
                "operation": "tool_completion",
                "provider": "openai",
                "model_name": "gpt-4.1-mini",
                "call_count": 5,
                "succeeded_count": 4,
                "failed_count": 1,
                "input_tokens": 1_000,
                "output_tokens": 200,
                "cached_input_tokens": 300,
                "reasoning_output_tokens": 20,
                "estimated_cost": Decimal("0.00057"),
                "unknown_cost_calls": 1,
                "average_latency_ms": Decimal("142.5"),
                "p95_latency_ms": 260.0,
            }
        ]
    )
    started_at = datetime(2026, 8, 1, tzinfo=UTC)
    ended_at = datetime(2026, 8, 2, tzinfo=UTC)

    summaries = asyncio.run(
        summarize_usage_logs(  # type: ignore[arg-type]
            connection,
            started_at=started_at,
            ended_at=ended_at,
            workload_type="report_morning",
            operation="tool_completion",
            user_id="user-1",
        )
    )

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.workload_type == "report_morning"
    assert summary.reasoning_output_tokens == 20
    assert summary.estimated_cost == Decimal("0.00057")
    assert summary.p95_latency_ms == Decimal("260.0")
    query, params = connection.executed[0]
    assert "GROUP BY workload_type, operation, provider, model_name" in query
    assert "percentile_cont(0.95)" in query
    assert params == (
        started_at,
        ended_at,
        "report_morning",
        "report_morning",
        "tool_completion",
        "tool_completion",
        "user-1",
        "user-1",
    )


def test_summarize_usage_logs_rejects_invalid_period() -> None:
    """종료 시각이 시작 시각보다 늦지 않은 조회를 거부한다."""
    connection = _SummaryConnection([])
    timestamp = datetime(2026, 8, 1, tzinfo=UTC)

    try:
        asyncio.run(
            summarize_usage_logs(  # type: ignore[arg-type]
                connection,
                started_at=timestamp,
                ended_at=timestamp,
            )
        )
    except ValueError as error:
        assert "종료 시각" in str(error)
    else:
        raise AssertionError("잘못된 조회 기간이 허용됐습니다.")
