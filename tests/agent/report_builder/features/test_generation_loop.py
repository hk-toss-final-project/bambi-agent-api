"""LangGraph 리포트 생성 루프 V2의 노드 구조·섹션 루프·조립 규칙을 검증한다.

LLM은 전부 monkeypatch로 대체한다(AGENTS.md §8 — pytest는 LLM 호출 없이
결정적으로 통과해야 한다). 실제 Provider 비교는 bench/report_generation_v2가 맡는다.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent.report_builder.features import generation_loop
from agent.report_builder.features.generation_loop import (
    GRADE_NO_EVIDENCE,
    GRADE_OK,
    GRADE_THIN,
    LANGGRAPH_GENERATION_PIPELINE_VERSION,
    LEGACY_GENERATION_PIPELINE_VERSION,
    assemble_sections,
    build_report_generation_graph_v2,
    build_report_section_graph_v2,
    coverage_note,
    default_generation_pipeline_version,
    plan_report_topics,
    section_max_revisions,
)
from agent.report_builder.features.critic import CriticVerdict
from agent.report_builder.features.researcher import ResearchOutcome
from shared.report_models import GeneratedReportContent, ReportContextDocument


def _document(reference: str, *, title: str = "문서") -> ReportContextDocument:
    """테스트용 근거 문서를 만든다."""
    return ReportContextDocument(
        reference=reference,
        document_version_id=f"ver-{reference}",
        chunk_id=f"chunk-{reference}",
        namespace_key="global/news",
        title=title,
        content=f"{title} 본문",
        url=f"https://example.test/{reference}",
        score=0.9,
    )


def _content(
    title: str, *, body: str = "본문", references: tuple[str, ...] = ("G1",)
) -> GeneratedReportContent:
    """테스트용 생성 콘텐츠를 만든다."""
    return GeneratedReportContent(
        title=title,
        summary=f"{title} 요약",
        body=body,
        citation_references=references,
        content_tags=(title,),
    )


def _section_state(topic: str, **overrides: Any) -> dict[str, Any]:
    """섹션 서브그래프 입력 상태를 만든다."""
    state: dict[str, Any] = {
        "topic": topic,
        "user_id": "user-1",
        "job_id": "job-1",
        "content_type": "interest_news_card",
        "language": "ko",
        "model": "gpt-4.1-mini",
        "read_pipeline_version": "legacy_v1",
        "max_revisions": 2,
    }
    state.update(overrides)
    return state


# ── 그래프 구조 ────────────────────────────────────────────────────────────


def test_section_graph_exposes_explicit_nodes() -> None:
    """섹션 서브그래프가 조사·배정·초안·검토·재작성·등급을 독립 노드로 드러낸다."""
    nodes = set(build_report_section_graph_v2().get_graph().nodes)

    assert nodes == {
        "__start__",
        "research_topic",
        "assess_topic",
        "draft_section",
        "critique_section",
        "revise_section",
        "grade_section",
        "__end__",
    }


def test_parent_graph_exposes_explicit_nodes() -> None:
    """상위 그래프가 계획·섹션 실행·조립·최종검토·저장을 독립 노드로 드러낸다."""
    nodes = set(build_report_generation_graph_v2(None).get_graph().nodes)

    assert nodes == {
        "__start__",
        "plan_topics",
        "run_sections",
        "assemble",
        "final_review",
        "persist",
        "__end__",
    }


# ── 버전 계약 ──────────────────────────────────────────────────────────────


def test_default_version_is_langgraph_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """기본값은 langgraph_v2다(2026-08-12 결정)."""
    monkeypatch.delenv("GENERATION_PIPELINE_VERSION", raising=False)

    assert default_generation_pipeline_version() == (
        LANGGRAPH_GENERATION_PIPELINE_VERSION
    )


def test_rollback_env_selects_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    """롤백 환경변수는 새 Job을 V1으로 되돌린다."""
    monkeypatch.setenv("GENERATION_PIPELINE_VERSION", "legacy_v1")

    assert default_generation_pipeline_version() == (
        LEGACY_GENERATION_PIPELINE_VERSION
    )


def test_unknown_version_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """알 수 없는 값은 거부하지 않고 기본값으로 되돌린다 — 접수를 막지 않는다."""
    monkeypatch.setenv("GENERATION_PIPELINE_VERSION", "v3")

    assert default_generation_pipeline_version() == (
        LANGGRAPH_GENERATION_PIPELINE_VERSION
    )


def test_section_max_revisions_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """섹션 재작성 상한은 환경변수로 조정한다."""
    monkeypatch.setenv("GENERATION_SECTION_MAX_REVISIONS", "0")

    assert section_max_revisions() == 0


# ── 섹션 루프 ──────────────────────────────────────────────────────────────


def test_section_revises_only_until_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """검토가 계속 지적해도 상한까지만 재작성하고 마지막 초안을 발행한다."""
    drafts: list[str] = []

    async def fake_research(*args: Any, **kwargs: Any) -> ResearchOutcome:
        """근거 두 건을 돌려준다."""
        return ResearchOutcome(documents=(_document("G1"), _document("G2")))

    def fake_generate(**kwargs: Any) -> GeneratedReportContent:
        """호출마다 다른 초안을 만들어 재작성 횟수를 셀 수 있게 한다."""
        drafts.append(str(kwargs.get("correction") or ""))
        return _content(f"초안{len(drafts)}")

    async def always_revise(*args: Any, **kwargs: Any) -> CriticVerdict:
        """항상 재작성을 요구한다."""
        return CriticVerdict(
            outcome="revise",
            should_regenerate=True,
            problem="근거 불일치",
            correction="근거를 다시 확인하라",
        )

    monkeypatch.setattr(generation_loop, "research_context_for_version", fake_research)
    monkeypatch.setattr(generation_loop, "focus_documents_on_topic", lambda t, d, **k: list(d))
    monkeypatch.setattr(generation_loop, "resolve_topic_intent", lambda *a, **k: "news")
    monkeypatch.setattr(
        generation_loop, "generate_report_content_with_quality", fake_generate
    )
    monkeypatch.setattr(generation_loop, "critic_enabled", lambda: True)
    monkeypatch.setattr(generation_loop, "review_report", always_revise)

    graph = build_report_section_graph_v2()
    final = asyncio.run(
        graph.ainvoke(
            _section_state("폭염", max_revisions=2),
            context=generation_loop.GenerationRuntimeContext(connection=None),
        )
    )

    # 최초 초안 1회 + 재작성 2회 = 생성 3회, revisions 는 2에서 멈춘다.
    assert len(drafts) == 3
    assert final["section"]["revisions"] == 2
    assert final["section"]["grade"] == GRADE_OK


def test_section_without_evidence_skips_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """근거가 없으면 초안을 만들지 않고 근거 없음 등급으로 끝낸다."""

    async def empty_research(*args: Any, **kwargs: Any) -> ResearchOutcome:
        """근거를 하나도 찾지 못한 조사 결과."""
        return ResearchOutcome(documents=())

    def unexpected_generate(**kwargs: Any) -> GeneratedReportContent:
        """근거 없는 주제에서 생성이 호출되면 실패시킨다."""
        raise AssertionError("근거가 없으면 초안을 만들면 안 됩니다.")

    monkeypatch.setattr(generation_loop, "research_context_for_version", empty_research)
    monkeypatch.setattr(generation_loop, "resolve_topic_intent", lambda *a, **k: "news")
    monkeypatch.setattr(
        generation_loop, "generate_report_content_with_quality", unexpected_generate
    )

    graph = build_report_section_graph_v2()
    final = asyncio.run(
        graph.ainvoke(
            _section_state("근거없는주제"),
            context=generation_loop.GenerationRuntimeContext(connection=None),
        )
    )

    assert final["section"]["grade"] == GRADE_NO_EVIDENCE
    assert final["section"]["content"] is None


def test_research_failure_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """조사가 터져도 예외를 올리지 않고 근거 없음으로 떨어진다."""

    async def broken_research(*args: Any, **kwargs: Any) -> ResearchOutcome:
        """조사 중 예외를 발생시킨다."""
        raise RuntimeError("agent down")

    monkeypatch.setattr(generation_loop, "research_context_for_version", broken_research)
    monkeypatch.setattr(generation_loop, "resolve_topic_intent", lambda *a, **k: "news")

    graph = build_report_section_graph_v2()
    final = asyncio.run(
        graph.ainvoke(
            _section_state("터지는주제"),
            context=generation_loop.GenerationRuntimeContext(connection=None),
        )
    )

    assert final["section"]["grade"] == GRADE_NO_EVIDENCE
    assert final["section"]["research_stat"]["failed"] is True


def test_thin_evidence_is_graded_but_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """근거가 하나뿐이면 thin 등급이지만 발행을 막지 않는다."""

    async def one_document(*args: Any, **kwargs: Any) -> ResearchOutcome:
        """근거 한 건만 돌려준다."""
        return ResearchOutcome(documents=(_document("G1"),))

    monkeypatch.setattr(generation_loop, "research_context_for_version", one_document)
    monkeypatch.setattr(generation_loop, "focus_documents_on_topic", lambda t, d, **k: list(d))
    monkeypatch.setattr(generation_loop, "resolve_topic_intent", lambda *a, **k: "news")
    monkeypatch.setattr(
        generation_loop,
        "generate_report_content_with_quality",
        lambda **kwargs: _content("얕은섹션"),
    )
    monkeypatch.setattr(generation_loop, "critic_enabled", lambda: False)

    graph = build_report_section_graph_v2()
    final = asyncio.run(
        graph.ainvoke(
            _section_state("얕은주제"),
            context=generation_loop.GenerationRuntimeContext(connection=None),
        )
    )

    assert final["section"]["grade"] == GRADE_THIN
    assert final["section"]["content"] is not None


# ── 조립 ───────────────────────────────────────────────────────────────────


def test_assemble_keeps_missing_topic_as_coverage_note() -> None:
    """근거 없는 주제를 삭제하지 않고 커버리지 노트로 남긴다."""
    sections = [
        {"topic": "폭염", "content": _content("폭염 정리"), "contexts": [_document("G1")]},
        {"topic": "환율", "content": None, "contexts": []},
    ]

    generated, contexts = assemble_sections(sections, fallback_topic="오늘의 브리핑")

    assert "### 폭염" in generated.body
    assert coverage_note("환율") in generated.body
    assert len(contexts) == 1


def test_assemble_merges_citations_without_duplicates() -> None:
    """섹션 인용을 합치되 중복은 제거하고 순서를 보존한다."""
    sections = [
        {
            "topic": "A",
            "content": _content("A", references=("G1", "G2")),
            "contexts": [_document("G1"), _document("G2")],
        },
        {
            "topic": "B",
            "content": _content("B", references=("G2", "G3")),
            "contexts": [_document("G2"), _document("G3")],
        },
    ]

    generated, contexts = assemble_sections(sections, fallback_topic="묶음")

    assert generated.citation_references == ("G1", "G2", "G3")
    assert [document.reference for document in contexts] == ["G1", "G2", "G3"]


def test_assemble_does_not_duplicate_existing_heading() -> None:
    """섹션 본문이 이미 같은 제목으로 시작하면 제목을 덧붙이지 않는다."""
    sections = [
        {
            "topic": "폭염",
            "content": _content("폭염", body="### 폭염\n\n본문"),
            "contexts": [_document("G1")],
        }
    ]

    generated, _ = assemble_sections(sections, fallback_topic="묶음")

    assert generated.body.count("### 폭염") == 1


def test_assemble_falls_back_to_request_topic_when_all_missing() -> None:
    """모든 주제가 근거 없음이면 리포트 제목은 요청 주제를 쓴다."""
    sections = [{"topic": "A", "content": None, "contexts": []}]

    generated, contexts = assemble_sections(sections, fallback_topic="오늘의 브리핑")

    assert generated.title == "오늘의 브리핑"
    assert contexts == []


# ── 주제 계획 ──────────────────────────────────────────────────────────────


def test_plan_topics_keeps_request_order_and_drops_duplicates() -> None:
    """요청 순서를 유지하고 중복 주제만 합친다.

    순서가 곧 섹션 순서라 정렬하면 안 된다(V1 topics 계약과 동일).
    """
    planned = plan_report_topics(
        "오늘의 브리핑", ["폭염", "환율", "폭염 ", "웹툰"]
    )

    assert planned == ["폭염", "환율", "웹툰"]


def test_plan_topics_uses_single_topic_when_topics_empty() -> None:
    """topics가 비면 topic 하나를 주제로 삼는다."""
    assert plan_report_topics("인덱스 튜닝", []) == ["인덱스 튜닝"]


def test_plan_topics_excludes_card_title_topic() -> None:
    """topics가 있으면 topic(카드 제목용)은 섹션 주제가 되지 않는다."""
    planned = plan_report_topics("오늘의 관심사 브리핑", ["폭염", "환율"])

    assert "오늘의 관심사 브리핑" not in planned


def test_plan_topics_rejects_empty_request() -> None:
    """주제가 하나도 없으면 명시적으로 거절한다."""
    with pytest.raises(ValueError):
        plan_report_topics("  ", [])
