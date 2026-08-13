"""LLM 사용량의 업무 귀속 Context와 실행 경계.

Job Payload를 호출마다 다시 해석하지 않도록 실행 시작 시 안정적인 업무 분류와
추적 식별자를 고정한다. 원문 입력·출력은 Context와 사용량 로그에 포함하지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

@dataclass(frozen=True, slots=True)
class LlmUsageContext:
    """한 API 요청 또는 Agent Job의 LLM 비용 귀속 정보."""

    feature_id: str
    workload_type: str
    user_id: str | None = None
    job_id: str | None = None
    generation_run_id: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    plan: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


_usage_context: ContextVar[LlmUsageContext | None] = ContextVar(
    "llm_usage_context",
    default=None,
)


@contextmanager
def llm_usage_context(context: LlmUsageContext) -> Iterator[LlmUsageContext]:
    """현재 실행 범위에 LLM 사용량 귀속 Context를 설정한다."""
    token = _usage_context.set(context)
    try:
        yield context
    finally:
        _usage_context.reset(token)


def current_llm_usage_context() -> LlmUsageContext | None:
    """현재 실행 범위의 LLM 사용량 귀속 Context를 반환한다."""
    return _usage_context.get()


def classify_llm_workload(
    *,
    job_type: str,
    feature_id: str,
    payload: Mapping[str, object],
) -> str:
    """Job 계약을 조회용 안정 업무 분류로 변환한다."""
    if job_type == "personal_wiki_build":
        trigger = str(payload.get("trigger") or "").strip().lower()
        if trigger == "maintenance" or feature_id == "WBA-002":
            return "wiki_maintenance"
        return "wiki_build"
    if job_type == "report_generation":
        generation_scope = str(payload.get("generation_scope") or "").upper()
        report_type = str(payload.get("report_type") or "").upper()
        if (
            generation_scope == "WIKI_BRIEFING"
            or report_type == "MORNING_BRIEFING"
        ):
            return "report_morning"
        return "report_on_demand"
    if job_type == "briefing_preparation":
        return "briefing_preparation"
    return "other"


def llm_usage_metadata_from_job(
    *,
    job_type: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    """민감한 업무 입력을 제외하고 조회에 필요한 Job 속성만 선별한다."""
    allowed_keys = (
        "generation_scope",
        "report_type",
        "execution_mode",
        "maintenance_pipeline_version",
        "read_pipeline_version",
        "mode",
        "trigger",
    )
    metadata: dict[str, object] = {"job_type": job_type}
    for key in allowed_keys:
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)) and value != "":
            metadata[key] = value
    return metadata
