"""검토자 에이전트(Critic)의 도구와 판정 처리를 검증한다.

LLM과 DB를 모두 대체하고, 검토자가 근거 원문을 도구로 꺼내 보는지와
응답이 깨졌을 때 발행을 막지 않는지를 확인한다.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent.llm.api import ToolLoopResult
from agent.report_builder.features import critic
from agent.report_builder.features.critic import (
    PASS,
    REVISE,
    UNAVAILABLE,
    build_critic_tools,
    parse_verdict,
    review_report,
)
from shared.report_models import GeneratedReportContent, ReportContextDocument


def _document(reference: str, *, title: str, content: str) -> ReportContextDocument:
    """테스트용 근거 문서를 만든다."""
    return ReportContextDocument(
        reference=reference,
        document_version_id=f"ver-{reference}",
        chunk_id=f"chunk-{reference}",
        namespace_key="global",
        title=title,
        content=content,
        url=None,
        score=0.9,
    )


def _content() -> GeneratedReportContent:
    """테스트용 리포트 초안을 만든다."""
    return GeneratedReportContent(
        title="코스피 급락",
        summary="코스피가 급락했습니다.",
        body="코스피는 시가총액 방식으로 산출됩니다[P1].",
        citation_references=("P1",),
    )


CONTEXTS = [
    _document("P1", title="코스피", content="코스피는 시가총액 방식으로 산출된다."),
    _document("P2", title="서킷 브레이커", content="급락 시 거래를 일시 중단한다."),
]


def _tools(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """이름으로 찾을 수 있는 검토 도구 사전을 만든다."""
    specs = build_critic_tools(
        object(),  # type: ignore[arg-type]
        user_id="user-1",
        contexts=CONTEXTS,
        topic_intent="news",
    )
    return {spec.name: spec for spec in specs}


def test_get_source_returns_full_body_for_a_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """참조 ID로 근거 원문을 돌려준다."""
    tools = _tools(monkeypatch)

    observation = tools["get_source"].run(reference="P1")

    assert "코스피는 시가총액 방식으로 산출된다" in observation


def test_get_source_lists_available_references_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """없는 참조를 물으면 사용 가능한 목록을 알려준다.

    검토자가 존재하지 않는 인용을 지어내면 여기서 드러난다.
    """
    tools = _tools(monkeypatch)

    observation = tools["get_source"].run(reference="P9")

    assert "P1" in observation and "P2" in observation


def test_draft_prompt_hides_source_bodies() -> None:
    """검토자에게 주는 초안에는 근거 원문이 들어가지 않는다.

    원문을 미리 주면 get_source를 쓸 이유가 없어져 도구가 장식이 된다.
    """
    prompt = critic._draft_prompt(_content(), CONTEXTS)

    assert "P1: 코스피" in prompt
    assert "시가총액 방식으로 산출된다" not in prompt


def test_parse_verdict_reads_revise_with_correction() -> None:
    """revise 판정과 교정 지시를 읽어들인다."""
    verdict = parse_verdict(
        '{"verdict":"revise","problem":"P1에 없는 내용","correction":"근거대로 고치세요"}'
    )

    assert verdict is not None
    assert verdict.outcome == REVISE
    assert verdict.should_regenerate is True
    assert verdict.correction == "근거대로 고치세요"


def test_parse_verdict_falls_back_to_problem_when_correction_missing() -> None:
    """교정 지시가 비면 문제 설명을 지시로 쓴다.

    무엇을 고치라는지 없으면 재작성해도 같은 글이 나온다.
    """
    verdict = parse_verdict('{"verdict":"revise","problem":"P1에 없는 내용"}')

    assert verdict is not None
    assert verdict.correction == "P1에 없는 내용"


def test_parse_verdict_rejects_broken_response() -> None:
    """JSON이 아니거나 판정 값이 이상하면 None을 반환한다."""
    assert parse_verdict("판정: 통과") is None
    assert parse_verdict('{"verdict":"maybe"}') is None


def test_review_passes_through_when_model_response_is_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """검토자 응답이 깨져도 발행을 막지 않는다."""

    async def broken_loop(*args: Any, **kwargs: Any) -> ToolLoopResult:
        """JSON이 아닌 응답을 반환한다."""
        return ToolLoopResult(text="음, 괜찮아 보입니다.")

    monkeypatch.setattr(critic, "run_tool_loop", broken_loop)

    verdict = asyncio.run(
        review_report(
            object(),  # type: ignore[arg-type]
            content=_content(),
            contexts=CONTEXTS,
            user_id="user-1",
            topic="코스피",
        )
    )

    assert verdict.outcome == UNAVAILABLE
    assert verdict.should_regenerate is False


def test_review_passes_through_when_loop_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """검토자 실행이 실패해도 발행을 막지 않는다."""

    async def broken_loop(*args: Any, **kwargs: Any) -> ToolLoopResult:
        """도구 루프 실행 중 오류를 재현한다."""
        raise RuntimeError("LLM 장애")

    monkeypatch.setattr(critic, "run_tool_loop", broken_loop)

    verdict = asyncio.run(
        review_report(
            object(),  # type: ignore[arg-type]
            content=_content(),
            contexts=CONTEXTS,
            user_id="user-1",
            topic="코스피",
        )
    )

    assert verdict.outcome == UNAVAILABLE
    assert verdict.should_regenerate is False


def test_review_skips_when_there_is_nothing_to_check() -> None:
    """근거가 없으면 검토를 건너뛴다(대조할 원문이 없다)."""
    verdict = asyncio.run(
        review_report(
            object(),  # type: ignore[arg-type]
            content=_content(),
            contexts=[],
            user_id="user-1",
            topic="코스피",
        )
    )

    assert verdict.outcome == UNAVAILABLE


def test_review_reports_revise_verdict_with_tool_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """검토자가 근거를 대조한 뒤 재작성 판정을 내리면 그대로 전달한다."""
    checked: list[str] = []

    async def fake_loop(system_prompt, user_prompt, tools, **kwargs: Any):
        """검토자가 get_source로 P1을 확인한 뒤 revise를 낸 상황을 재현한다."""
        source = {spec.name: spec for spec in tools}["get_source"]
        checked.append(source.run(reference="P1"))
        return ToolLoopResult(
            text='{"verdict":"revise","problem":"당일 급락 사실이 빠졌다",'
            '"correction":"급락 폭과 서킷 브레이커 발동을 본문에 넣으세요"}',
            stop_reason="final",
        )

    monkeypatch.setattr(critic, "run_tool_loop", fake_loop)

    verdict = asyncio.run(
        review_report(
            object(),  # type: ignore[arg-type]
            content=_content(),
            contexts=CONTEXTS,
            user_id="user-1",
            topic="코스피",
        )
    )

    assert checked and "시가총액" in checked[0]
    assert verdict.outcome == REVISE
    assert verdict.should_regenerate is True
    assert "서킷 브레이커" in verdict.correction


def test_review_accepts_pass_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """문제가 없으면 통과 판정을 그대로 전달한다."""

    async def fake_loop(*args: Any, **kwargs: Any) -> ToolLoopResult:
        """통과 판정을 반환한다."""
        return ToolLoopResult(text='{"verdict":"pass","problem":"","correction":""}')

    monkeypatch.setattr(critic, "run_tool_loop", fake_loop)

    verdict = asyncio.run(
        review_report(
            object(),  # type: ignore[arg-type]
            content=_content(),
            contexts=CONTEXTS,
            user_id="user-1",
            topic="코스피",
        )
    )

    assert verdict.outcome == PASS
    assert verdict.should_regenerate is False


def test_critic_prompt_forbids_guessing_omissions() -> None:
    """빠진 사실 지적은 검색으로 확인한 뒤에만 하도록 지시한다.

    이 원칙이 없으면 검토자가 "이것도 다뤄야 한다"고 지어내 무한 재작성이 된다.
    """
    assert "search_pool로 그 자료가 실제로 있는지 먼저 확인" in critic.SYSTEM_PROMPT
    assert "추측으로" in critic.SYSTEM_PROMPT
