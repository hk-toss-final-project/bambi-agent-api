"""자료 조사 에이전트(Researcher)의 도구와 수집 결과를 검증한다.

LLM과 DB를 모두 대체해, 도구가 실제로 자료를 모으고 중복을 걸러내는지와
LLM이 고른 도구 호출이 근거 문서로 이어지는지를 확인한다.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import pytest

from agent.llm.api import ToolLoopResult
from agent.report_builder.features import researcher
from agent.report_builder.features.researcher import (
    DocumentCollector,
    build_research_tools,
    research_context,
)
from shared.report_models import ReportContextDocument


def _document(
    reference: str,
    *,
    title: str = "제목",
    namespace: str = "global",
    url: str | None = None,
    score: float = 0.9,
) -> ReportContextDocument:
    """테스트용 근거 문서를 만든다."""
    return ReportContextDocument(
        reference=reference,
        document_version_id=f"ver-{reference}",
        chunk_id=f"chunk-{reference}",
        namespace_key=namespace,
        title=title,
        content=f"{title} 본문 내용",
        url=url,
        score=score,
    )


class _FakeConnection:
    """transaction()만 지원하는 DB 연결 Test Double."""

    @asynccontextmanager
    async def transaction(self):  # type: ignore[no-untyped-def]
        """아무것도 하지 않는 트랜잭션 구간을 연다."""
        yield self


def _patch_db(
    monkeypatch: pytest.MonkeyPatch, hybrid: list[ReportContextDocument]
) -> list[str]:
    """풀 검색 경로의 DB 호출을 대체하고, 사용된 검색어를 기록한다."""
    queries: list[str] = []

    async def fake_prag_003(connection, *, user_id, query, **kwargs):
        """검색어를 기록하고 미리 준 문서를 반환한다."""
        queries.append(query)
        return hybrid

    async def fake_scope(connection, *, user_id):
        """RLS Scope 설정을 생략한다."""

    async def fake_freshness(connection, ids):
        """발행 시각 조회를 생략한다."""
        return {}

    monkeypatch.setattr(researcher, "prag_003", fake_prag_003)
    monkeypatch.setattr(researcher, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(researcher, "load_global_document_freshness", fake_freshness)
    monkeypatch.setattr(
        researcher, "select_pool_documents", lambda docs, **kwargs: list(docs)
    )
    return queries


def _tools(
    monkeypatch: pytest.MonkeyPatch,
    collector: DocumentCollector,
    hybrid: list[ReportContextDocument],
) -> dict[str, Any]:
    """이름으로 찾을 수 있는 도구 사전을 만든다."""
    _patch_db(monkeypatch, hybrid)
    specs = build_research_tools(
        _FakeConnection(),  # type: ignore[arg-type]
        user_id="user-1",
        topic_intent="news",
        collector=collector,
    )
    return {spec.name: spec for spec in specs}


def test_search_pool_tool_collects_documents_and_reports_titles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """풀 검색 도구가 문서를 모으고 제목이 담긴 관찰을 돌려준다."""
    collector = DocumentCollector()
    hybrid = [_document("G1", title="코스피 급락"), _document("G2", title="서킷 발동")]
    tools = _tools(monkeypatch, collector, hybrid)

    observation = asyncio.run(tools["search_pool"].run(query="코스피"))

    assert "2건" in observation
    assert "코스피 급락" in observation
    assert len(collector.documents) == 2


def test_search_pool_tool_deduplicates_across_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """같은 문서가 다시 걸리면 두 번 모으지 않는다.

    LLM이 연관 키워드로 검색을 넓히면 결과가 겹치므로 중복 제거가 필요하다.
    """
    collector = DocumentCollector()
    hybrid = [_document("G1", url="https://example.com/a")]
    tools = _tools(monkeypatch, collector, hybrid)

    asyncio.run(tools["search_pool"].run(query="코스피"))
    second = asyncio.run(tools["search_pool"].run(query="서킷 브레이커"))

    assert len(collector.documents) == 1
    assert second == "결과 없음."


def test_collector_renumbers_references_across_searches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """검색을 여러 번 해도 참조 번호가 겹치지 않게 다시 매긴다.

    검색은 호출마다 P1부터 다시 붙인다. 그대로 두면 하류의
    select_generation_context가 같은 참조를 중복으로 보고 문서를 버린다.
    (2026-07-30 실측: 7건 중 P4가 3건이라 2건이 사라졌다.)
    """
    collector = DocumentCollector()
    first = [
        _document("P1", title="코스피", url="https://example.com/1"),
        _document("P2", title="서킷 브레이커", url="https://example.com/2"),
    ]
    second = [
        _document("P1", title="예탁금", url="https://example.com/3"),
        _document("P2", title="시가총액", url="https://example.com/4"),
    ]

    collector.add(first)
    collector.add(second)

    references = [document.reference for document in collector.documents]
    assert references == ["P1", "P2", "P3", "P4"]
    assert len(set(references)) == len(references)


def test_collector_keeps_reference_prefix_per_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """저장 자료(P)와 실시간 수집(L)의 접두 문자를 각각 유지한다."""
    collector = DocumentCollector()

    collector.add([_document("P1", url="https://example.com/1")])
    collector.add([_document("L1", url="https://example.com/2")])
    collector.add([_document("P1", url="https://example.com/3")])

    assert [document.reference for document in collector.documents] == [
        "P1",
        "L1",
        "P2",
    ]


def test_search_pool_tool_rejects_blank_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """빈 검색어는 DB를 부르지 않고 안내를 돌려준다."""
    collector = DocumentCollector()
    queries = _patch_db(monkeypatch, [])
    specs = build_research_tools(
        _FakeConnection(),  # type: ignore[arg-type]
        user_id="user-1",
        topic_intent="news",
        collector=collector,
    )
    search = {spec.name: spec for spec in specs}["search_pool"]

    observation = asyncio.run(search.run(query="  "))

    assert observation == "검색어가 비어 있다."
    assert queries == []


def test_live_collection_is_not_exposed_as_a_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실시간 수집은 도구로 노출하지 않는다.

    언제 부를지가 "근거가 몇 건인가"에 달린 셈의 문제라 LLM에게 맡기지 않는다.
    도구로 남겨두면 프롬프트에서 언급을 빼도 모델이 임의로 부를 수 있다.
    """
    tools = _tools(monkeypatch, DocumentCollector(), [])

    assert list(tools) == ["search_pool"]


def _run_research(
    monkeypatch: pytest.MonkeyPatch, found: list[ReportContextDocument]
) -> tuple[object, list[str]]:
    """검색이 주어진 문서를 찾은 상황으로 조사를 실행하고 수집 호출을 기록한다."""
    _patch_db(monkeypatch, found)
    collected: list[str] = []

    async def fake_loop(system_prompt, user_prompt, tools, **kwargs):
        """LLM이 search_pool을 한 번 고른 상황을 재현한다."""
        chosen = {spec.name: spec for spec in tools}["search_pool"]
        await chosen.run(query="코스피")
        return ToolLoopResult(text="모았다.", stop_reason="final")

    def fake_collect(topic, user_id, *, model):
        """실시간 수집 호출을 기록하고 문서 한 건을 반환한다."""
        collected.append(topic)
        return [_document("L1", title="새 기사", url="https://example.com/live")]

    monkeypatch.setattr(researcher, "run_tool_loop", fake_loop)
    monkeypatch.setattr(researcher, "collect_live_context", fake_collect)

    outcome = asyncio.run(
        research_context(
            _FakeConnection(),  # type: ignore[arg-type]
            topic="코스피",
            user_id="user-1",
        )
    )
    return outcome, collected


def test_live_collection_runs_when_stored_documents_fall_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """저장 자료가 기준에 못 미치면 코드가 실시간 수집을 부른다."""
    outcome, collected = _run_research(
        monkeypatch, [_document("G1", title="코스피 급락", url="https://example.com/a")]
    )

    assert collected == ["코스피"]
    assert [document.title for document in outcome.documents] == [
        "코스피 급락",
        "새 기사",
    ]


def test_live_collection_is_skipped_when_stored_documents_suffice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """저장 자료가 충분하면 실시간 수집을 부르지 않는다.

    이 판정이 LLM에게 있을 때 정확도가 80%였다(2026-07-31 벤치마크).
    """
    found = [
        _document(f"G{n}", title=f"기사 {n}", url=f"https://example.com/{n}")
        for n in range(1, 4)
    ]

    outcome, collected = _run_research(monkeypatch, found)

    assert collected == []
    assert len(outcome.documents) == 3


def test_research_survives_live_collection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실시간 수집이 실패해도 지금까지 모은 근거는 살린다."""
    _patch_db(monkeypatch, [_document("G1", title="코스피", url="https://x/1")])

    async def fake_loop(system_prompt, user_prompt, tools, **kwargs):
        """검색 한 번만 수행한다."""
        await {spec.name: spec for spec in tools}["search_pool"].run(query="코스피")
        return ToolLoopResult(text="모았다.", stop_reason="final")

    def broken_collect(topic, user_id, *, model):
        """수집 중 오류를 재현한다."""
        raise RuntimeError("네트워크 실패")

    monkeypatch.setattr(researcher, "run_tool_loop", fake_loop)
    monkeypatch.setattr(researcher, "collect_live_context", broken_collect)

    outcome = asyncio.run(
        research_context(
            _FakeConnection(),  # type: ignore[arg-type]
            topic="코스피",
            user_id="user-1",
        )
    )

    assert [document.title for document in outcome.documents] == ["코스피"]


def test_research_prompt_focuses_on_search_only() -> None:
    """조사 지침이 검색어 확장에만 집중하고 수집 판단은 다루지 않는다.

    "몇 건이면 충분한가"를 프롬프트에 넣었을 때 판단 정확도가 80%에 그쳤고,
    문구를 두 번 고쳐도 과호출이 과소호출로 바뀔 뿐이었다(2026-07-31 벤치마크).
    그 판정은 is_pool_sufficient가 맡는다.
    """
    assert "주제어 하나로만 찾지 마라" in researcher.SYSTEM_PROMPT
    assert "collect_live" not in researcher.SYSTEM_PROMPT
