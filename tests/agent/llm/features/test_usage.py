"""LLM 사용량 Context의 업무 분류와 Metadata 최소화를 검증한다."""

from agent.llm.api import (
    LlmUsageContext,
    classify_llm_workload,
    current_llm_usage_context,
    llm_usage_context,
    llm_usage_metadata_from_job,
)


def test_classify_llm_workload_separates_wiki_build_and_maintenance() -> None:
    """같은 Wiki Job 유형에서도 일반 Build와 정기 유지를 분리한다."""
    assert (
        classify_llm_workload(
            job_type="personal_wiki_build",
            feature_id="SVC-003",
            payload={"mode": "incremental"},
        )
        == "wiki_build"
    )
    assert (
        classify_llm_workload(
            job_type="personal_wiki_build",
            feature_id="WBA-002",
            payload={"mode": "full_rebuild", "trigger": "maintenance"},
        )
        == "wiki_maintenance"
    )


def test_classify_llm_workload_separates_morning_and_on_demand_reports() -> None:
    """아침 브리핑과 나머지 리포트 생성 호출을 별도 업무로 분류한다."""
    assert (
        classify_llm_workload(
            job_type="report_generation",
            feature_id="SVC-008",
            payload={"generation_scope": "WIKI_BRIEFING"},
        )
        == "report_morning"
    )
    assert (
        classify_llm_workload(
            job_type="report_generation",
            feature_id="SVC-008",
            payload={"report_type": "ON_DEMAND"},
        )
        == "report_on_demand"
    )


def test_llm_usage_metadata_excludes_topic_and_content() -> None:
    """조회 Metadata에는 Pipeline 속성만 남기고 사용자 주제·본문은 제외한다."""
    metadata = llm_usage_metadata_from_job(
        job_type="report_generation",
        payload={
            "generation_scope": "SINGLE_TOPIC",
            "report_type": "ON_DEMAND",
            "topic": "저장하면 안 되는 사용자 주제",
            "batch_contexts": [{"content": "저장하면 안 되는 원문"}],
        },
    )

    assert metadata == {
        "job_type": "report_generation",
        "generation_scope": "SINGLE_TOPIC",
        "report_type": "ON_DEMAND",
    }


def test_llm_usage_context_is_scoped_and_restored() -> None:
    """사용량 Context는 실행 범위 안에서만 보이고 종료 후 원상 복구된다."""
    context = LlmUsageContext(
        feature_id="SVC-008",
        workload_type="report_on_demand",
        user_id="user-1",
    )

    assert current_llm_usage_context() is None
    with llm_usage_context(context):
        assert current_llm_usage_context() is context
    assert current_llm_usage_context() is None
