"""변경점 추적 워커(Diff·Compose·Impact)의 파싱과 프롬프트 계약을 검증한다.

LLM은 모두 대체한다. 확인하는 것은 세 가지다 — (1) Diff worker가 팩트 구조와
갱신 대상 ID를 제대로 뽑는지, (2) 첫 실행에는 도구를 주지 않는지, (3) 두 워커의
프롬프트가 인용 마커를 실제로 요구하고 응답의 마커가 보존되는지.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import pytest

from agent.change_history.features import compose as compose_module
from agent.change_history.features import diff as diff_module
from agent.change_history.features import impact as impact_module
from agent.change_history.features.compose import (
    describe_facts_for_writing,
    parse_compose_response,
)
from agent.change_history.features.diff import (
    DiffFact,
    build_diff_tools,
    describe_base_facts,
    extract_delta_facts,
    parse_diff_facts,
)
from agent.change_history.features.impact import infer_impact, parse_impact_response
from agent.llm.api import LlmCompletion, ToolLoopResult
from shared.change_history_models import ChangeHistoryFact
from shared.report_models import ReportContextDocument


def _document(reference: str, *, url: str | None = None) -> ReportContextDocument:
    """테스트용 근거 문서를 만든다."""
    return ReportContextDocument(
        reference=reference,
        document_version_id=f"ver-{reference}",
        chunk_id=f"chunk-{reference}",
        namespace_key="global",
        title=f"{reference} 기사",
        content="B사가 HBM4 양산을 2026년 3분기로 연기했다.",
        url=url,
        score=0.8,
    )


CONTEXTS = [_document("G1", url="https://example.test/g1"), _document("P1")]


def _fact(**overrides: Any) -> DiffFact:
    """테스트용 팩트를 만든다."""
    values: dict[str, Any] = {
        "verdict": "new",
        "subject": "B사 HBM4",
        "attribute": "양산 일정",
        "fact_value": "2026-3Q",
        "today_statement": "B사가 HBM4 양산을 2026-3Q로 연기했다.",
        "source_reference": "G1",
    }
    values.update(overrides)
    return DiffFact(**values)


def test_parse_diff_facts_reads_three_element_facts() -> None:
    """팩트를 (subject, attribute, fact_value) 세 요소로 읽는다."""
    text = (
        '{"facts":[{"verdict":"updated","updates_fact_id":"fact-1",'
        '"subject":"B사 HBM4","attribute":"양산 일정","fact_value":"2026-3Q",'
        '"today_statement":"양산이 연기됐다.","date_expression":"2026년 3분기",'
        '"source_reference":"G1"}]}'
    )

    facts = parse_diff_facts(text, contexts=CONTEXTS)

    assert len(facts) == 1
    assert facts[0].verdict == "updated"
    assert facts[0].updates_fact_id == "fact-1"
    assert facts[0].subject == "B사 HBM4"
    # source_url은 LLM이 아니라 참조 ID로 근거 문서에서 찾아 채운다.
    assert facts[0].source_url == "https://example.test/g1"


def test_parse_diff_facts_skips_broken_items_but_keeps_the_rest() -> None:
    """항목 하나가 깨져도 나머지 팩트는 살린다."""
    text = (
        '{"facts":[{"verdict":"nonsense","subject":"A","attribute":"B",'
        '"today_statement":"x"},'
        '{"verdict":"new","subject":"B사 HBM4","attribute":"양산 일정",'
        '"fact_value":"2026-3Q","today_statement":"연기됐다.","source_reference":"G1"}]}'
    )

    facts = parse_diff_facts(text, contexts=CONTEXTS)

    assert [fact.subject for fact in facts] == ["B사 HBM4"]


def test_parse_diff_facts_drops_unknown_citation_reference() -> None:
    """근거 목록에 없는 참조는 비운다(저장 시 Citation 조회가 깨지지 않게)."""
    text = (
        '{"facts":[{"verdict":"new","subject":"A사","attribute":"가격",'
        '"fact_value":"1000","today_statement":"올랐다.","source_reference":"G9"}]}'
    )

    facts = parse_diff_facts(text, contexts=CONTEXTS)

    assert facts[0].source_reference == ""
    assert facts[0].source_url == ""


def test_parse_diff_facts_returns_empty_for_broken_json() -> None:
    """응답 자체가 JSON이 아니면 빈 목록을 돌려준다(예외를 올리지 않는다)."""
    assert parse_diff_facts("무슨 말인지 모르겠다", contexts=CONTEXTS) == []


def test_describe_base_facts_includes_ids() -> None:
    """과거 팩트 관찰에는 ID가 반드시 들어간다(갱신 판정의 재료다)."""
    observation = describe_base_facts(
        [
            ChangeHistoryFact(
                fact_id="fact-1",
                subject="B사 HBM4",
                attribute="양산 일정",
                fact_value="2026-2Q",
                statement="B사 HBM4 양산은 2026-2Q다.",
                verdict="new",
            )
        ]
    )

    assert "id=fact-1" in observation
    assert "2026-2Q" in observation


def test_first_run_gives_no_tool_and_marks_everything_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """첫 실행에는 과거 대조만 생략하고 출력 형식은 그대로 유지한다."""
    seen: dict[str, Any] = {}

    async def fake_loop(
        system_prompt: str, user_prompt: str, tools: Any, **kwargs: Any
    ) -> ToolLoopResult:
        """도구 목록과 프롬프트를 기록하고 고정 응답을 돌려준다."""
        seen["tools"] = list(tools)
        seen["system"] = system_prompt
        return ToolLoopResult(
            text=(
                '{"facts":[{"verdict":"new","updates_fact_id":null,'
                '"subject":"B사 HBM4","attribute":"양산 일정","fact_value":"2026-3Q",'
                '"today_statement":"연기됐다.","source_reference":"G1"}]}'
            )
        )

    monkeypatch.setattr(diff_module, "run_tool_loop", fake_loop)

    outcome = asyncio.run(
        extract_delta_facts(
            object(),  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
            contexts=CONTEXTS,
            base_available=False,
        )
    )

    assert seen["tools"] == []  # 과거 대조 도구를 주지 않는다
    assert "첫 실행" in seen["system"]
    assert [fact.verdict for fact in outcome.facts] == ["new"]
    assert outcome.base_consulted is False


def test_diff_worker_gets_the_search_tool_when_base_exists() -> None:
    """Base가 있으면 읽기 전용 조회 도구 하나를 준다."""
    tools = build_diff_tools(
        object(),  # type: ignore[arg-type]
        user_id="user-1",
        topic="반도체",
        usage={},
    )

    assert [tool.name for tool in tools] == ["search_base_facts"]
    # topic은 클로저에 고정한다 — LLM이 다른 주제 팩트를 끌어오지 못하게 한다.
    assert "topic" not in tools[0].parameters["properties"]


def test_diff_worker_returns_empty_when_llm_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM이 죽어도 예외를 올리지 않고 빈 결과로 넘어간다."""

    async def broken_loop(*args: Any, **kwargs: Any) -> ToolLoopResult:
        """도구 루프 장애를 재현한다."""
        raise RuntimeError("provider down")

    monkeypatch.setattr(diff_module, "run_tool_loop", broken_loop)

    outcome = asyncio.run(
        extract_delta_facts(
            object(),  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
            contexts=CONTEXTS,
            base_available=True,
        )
    )

    assert outcome.facts == ()


def test_compose_prompt_requires_citation_markers() -> None:
    """Compose 프롬프트가 인용 마커를 실제로 요구한다.

    마커가 없으면 뒤에 오는 Critic이 대조할 대상이 없어 빈 검토를 통과시킨다.
    """
    assert "[G2]" in compose_module.SYSTEM_PROMPT
    assert "참조 ID" in compose_module.SYSTEM_PROMPT
    # 팩트 목록에도 참조 ID를 붙여 줘야 워커가 인용할 수 있다.
    assert "[G1]" in describe_facts_for_writing([_fact()])


def test_impact_prompt_requires_citation_markers() -> None:
    """Impact 프롬프트도 같은 인용 마커 규칙을 요구한다."""
    assert "[G2]" in impact_module.SYSTEM_PROMPT
    assert "참조 ID" in impact_module.SYSTEM_PROMPT


def test_compose_output_keeps_citation_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compose 응답의 인용 마커가 결과까지 그대로 보존된다."""

    def fake_completion(system: str, user: str, **kwargs: Any) -> LlmCompletion:
        """고정 JSON 응답을 돌려준다."""
        return LlmCompletion(
            text=(
                '{"title":"반도체 브리핑","summary":"요약 [G1]",'
                '"overview":"B사가 양산을 연기했습니다 [G1].",'
                '"timeline":[{"fact_index":0,"date":"2026-08-05","precision":"day",'
                '"description":"연기 발표 [G1]"}]}'
            ),
            model="test",
            input_tokens=10,
            output_tokens=20,
        )

    monkeypatch.setattr(compose_module, "complete_with_usage", fake_completion)

    outcome = compose_module.compose_overview_and_timeline(
        topic="반도체",
        facts=[_fact()],
        reference_date=date(2026, 8, 5),
    )

    assert "[G1]" in outcome.overview
    assert outcome.timeline[0].raw_date == "2026-08-05"
    assert "[G1]" in outcome.timeline[0].description
    assert outcome.failed is False


def test_compose_marks_failure_on_broken_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """응답을 해석하지 못하면 failed=True로 알려 Supervisor가 재작업하게 한다."""
    monkeypatch.setattr(
        compose_module,
        "complete_with_usage",
        lambda *args, **kwargs: LlmCompletion(
            text="not json", model="test", input_tokens=1, output_tokens=1
        ),
    )

    outcome = compose_module.compose_overview_and_timeline(
        topic="반도체", facts=[_fact()], reference_date=date(2026, 8, 5)
    )

    assert outcome.failed is True


def test_impact_output_keeps_citation_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Impact 응답의 인용 마커와 행동 지침이 결과까지 보존된다."""
    monkeypatch.setattr(
        impact_module,
        "complete_with_usage",
        lambda *args, **kwargs: LlmCompletion(
            text=(
                '{"implications":"공급 지연이 길어질 수 있습니다 [G1].",'
                '"actions":["재고 확인","대체 공급선 점검"]}'
            ),
            model="test",
            input_tokens=5,
            output_tokens=7,
        ),
    )

    outcome = infer_impact(topic="반도체", facts=[_fact()])

    assert "[G1]" in outcome.implications
    assert outcome.actions == ("재고 확인", "대체 공급선 점검")


def test_parse_impact_response_rejects_empty_implications() -> None:
    """파급효과 본문이 비면 실패로 본다."""
    assert parse_impact_response('{"implications":"","actions":[]}') is None


def test_parse_compose_response_rejects_empty_overview() -> None:
    """Overview가 비면 실패로 본다(조립할 내용이 없다)."""
    assert parse_compose_response('{"overview":"","timeline":[]}') is None
