"""LLM 사용량 가격 계산과 Batch 저장을 검증한다."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from agent.llm.api import LlmCallObservation, LlmUsageContext
from infrastructure.persistence.api import (
    ModelPricing,
    UsageLogRecord,
    apply_model_pricing,
    calculate_estimated_cost,
    price_and_insert_usage_logs,
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
    insert_payload = connection.executed[1][1][0].obj  # type: ignore[attr-defined]
    assert [item["cost_status"] for item in insert_payload] == [
        "calculated",
        "calculated",
    ]
    assert insert_payload[0]["pricing_snapshot"]["version"] == 1
    assert "prompt" not in insert_payload[0]["metadata"]
    assert "response" not in insert_payload[0]["metadata"]


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
