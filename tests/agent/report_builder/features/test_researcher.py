"""자료 조사 에이전트(Researcher)의 도구와 수집 결과를 검증한다.

LLM과 DB를 모두 대체해, 도구가 실제로 자료를 모으고 중복을 걸러내는지와
LLM이 고른 도구 호출이 근거 문서로 이어지는지를 확인한다.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from agent.llm.api import ToolLoopResult
from agent.report_builder.features import researcher
from agent.report_builder.features.researcher import (
    DocumentCollector,
    WikiNavigationSession,
    build_research_tools,
    load_navigation_snapshot_packet,
    merge_context_documents,
    research_context,
)
from shared.report_models import ReportContextDocument
from shared.wiki_navigation_models import (
    WikiNavigationCandidate,
    WikiNavigationExcerpt,
    WikiNavigationPacket,
    WikiNavigationPage,
    WikiNavigationSource,
)


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

    async def fake_global_search(
        connection, *, user_id, query, topic_intent="news"
    ):
        """Reader의 Global 전용 검색 결과와 검색어를 기록한다."""
        queries.append(query)
        return [document for document in hybrid if document.namespace_key == "global"]

    monkeypatch.setattr(researcher, "prag_003", fake_prag_003)
    monkeypatch.setattr(researcher, "embed_wiki_queries", lambda queries: {})
    monkeypatch.setattr(researcher, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(researcher, "load_global_document_freshness", fake_freshness)
    monkeypatch.setattr(researcher, "search_global_documents", fake_global_search)
    monkeypatch.setattr(
        researcher, "select_pool_documents", lambda docs, **kwargs: list(docs)
    )
    # 주제 관련성 판정은 임베딩 API를 부른다. 단위 테스트는 네트워크를 타지
    # 않아야 하므로 "풀 문서가 있으면 관련 있다"로 대체한다. 판정 규칙 자체는
    # tests/agent/report_builder/features/test_pool_context.py가 검증한다.
    monkeypatch.setattr(
        researcher, "is_pool_relevant", lambda topic, documents: bool(documents)
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


def test_wiki_search_exposes_all_thirty_candidates_without_degree_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reader가 연결 수와 무관하게 30번째 후보까지 직접 볼 수 있다."""
    collector = DocumentCollector()
    session = WikiNavigationSession()
    connection = _FakeConnection()
    now = datetime(2026, 8, 10, tzinfo=UTC)
    candidates = [
        WikiNavigationCandidate(
            document_id=f"doc-{index}",
            document_version_id=f"version-{index}",
            document_kind="entity",
            document_key=f"key-{index}",
            file_path=f"entities/{index}.md",
            title="DBeaver" if index == 1 else ("삼성전자" if index == 30 else f"후보 {index}"),
            aliases=(),
            summary=f"후보 {index} 요약",
            updated_at=now,
            keyword_rank=index,
            rrf_score=1.0 / (60 + index),
        )
        for index in range(1, 31)
    ]
    calls: list[tuple[object, int]] = []

    async def fake_wnav_001(connection_arg, **kwargs):
        """같은 Connection과 후보 상한을 기록하고 30개를 반환한다."""
        calls.append((connection_arg, kwargs["limit"]))
        return candidates

    monkeypatch.setattr(researcher, "wnav_001", fake_wnav_001)
    monkeypatch.setattr(researcher, "embed_wiki_queries", lambda queries: {})
    tools = build_research_tools(
        connection,  # type: ignore[arg-type]
        user_id="user-1",
        topic_intent="news",
        collector=collector,
        navigation_session=session,
    )

    observation = asyncio.run(
        {tool.name: tool for tool in tools}["wiki_search"].run(query="삼성전자")
    )

    assert calls == [(connection, 30)]
    assert len(session.candidates) == 30
    assert "[version-1] DBeaver" in observation
    assert "[version-30] 삼성전자" in observation
    assert "degree" not in observation


def test_wiki_read_uses_selected_version_and_includes_saved_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reader가 고른 후보만 같은 Connection으로 읽고 저장 시각을 Context에 싣는다."""
    collector = DocumentCollector()
    session = WikiNavigationSession()
    connection = _FakeConnection()
    now = datetime(2026, 8, 10, 9, 30, tzinfo=UTC)
    candidate = WikiNavigationCandidate(
        document_id="doc-samsung",
        document_version_id="version-samsung",
        document_kind="entity",
        document_key="삼성전자",
        file_path="entities/삼성전자.md",
        title="삼성전자",
        aliases=(),
        summary="반도체 기업",
        updated_at=now,
        keyword_rank=30,
        rrf_score=0.01,
    )
    selected_calls: list[tuple[object, tuple[str, ...], str | None]] = []

    async def fake_wnav_001(connection_arg, **kwargs):
        """Reader 선택용 후보 한 건을 반환한다."""
        return [candidate]

    async def fake_wnav_006(connection_arg, **kwargs):
        """선택 Version과 Wiki Build를 기록하고 Source 포함 Packet을 반환한다."""
        selected_calls.append(
            (
                connection_arg,
                tuple(kwargs["selected_document_version_ids"]),
                kwargs["wiki_version_id"],
            )
        )
        page = WikiNavigationPage(
            document_id=candidate.document_id,
            document_version_id=candidate.document_version_id,
            document_kind=candidate.document_kind,
            document_key=candidate.document_key,
            file_path=candidate.file_path,
            title=candidate.title,
            aliases=(),
            summary=candidate.summary,
            markdown="# 삼성전자",
            version=2,
            updated_at=now,
            role="seed",
            excerpts=(
                WikiNavigationExcerpt(
                    chunk_id="chunk-samsung",
                    chunk_index=0,
                    content="사용자는 삼성전자 반도체에 관심을 보였다.",
                ),
            ),
        )
        source = WikiNavigationSource(
            wiki_document_version_id=candidate.document_version_id,
            source_document_id="source-1",
            source_document_version_id="source-version-1",
            source_type="web_clipping",
            title="삼성전자 저장 글",
            url="https://example.com/samsung",
            relation_type="derived_from",
            saved_at=now,
            saved_at_source="event_occurred_at",
            stored_at=now,
            published_at=None,
            clipped_on=None,
        )
        return WikiNavigationPacket(
            query=kwargs["query"],
            wiki_version_id=kwargs["wiki_version_id"],
            candidates=(candidate,),
            pages=(page,),
            relations=(),
            sources=(source,),
            trace=(),
        )

    monkeypatch.setattr(researcher, "wnav_001", fake_wnav_001)
    monkeypatch.setattr(researcher, "wnav_006", fake_wnav_006)
    monkeypatch.setattr(researcher, "embed_wiki_queries", lambda queries: {})
    tools = {
        tool.name: tool
        for tool in build_research_tools(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic_intent="news",
            collector=collector,
            navigation_session=session,
            wiki_version_id="wiki-build-7",
        )
    }

    asyncio.run(tools["wiki_search"].run(query="최근 삼성전자 관심"))
    observation = asyncio.run(
        tools["wiki_read"].run(document_version_ids=["version-samsung"])
    )

    assert selected_calls == [
        (connection, ("version-samsung",), "wiki-build-7")
    ]
    assert len(session.packets) == 1
    assert len(collector.documents) == 1
    assert "saved_at=2026-08-10T09:30:00+00:00" in collector.documents[0].content
    assert collector.documents[0].context_role == "wiki_navigator_seed"
    assert "저장 Source 1건" in observation


def test_retry_restores_exact_page_and_source_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """같은 Job 재시도는 새 Seed 선택 없이 저장된 Page·Source를 복원한다."""
    connection = _FakeConnection()
    now = datetime(2026, 8, 10, 9, 30, tzinfo=UTC)
    calls: list[tuple[object, tuple[str, ...], str | None]] = []

    async def fake_wnav_002(connection_arg, **kwargs):
        """Snapshot에 고정된 정확한 Version ID 조회를 기록한다."""
        calls.append(
            (
                connection_arg,
                tuple(kwargs["document_version_ids"]),
                kwargs["wiki_version_id"],
            )
        )
        return [
            WikiNavigationPage(
                document_id="doc-samsung",
                document_version_id="version-samsung",
                document_kind="entity",
                document_key="삼성전자",
                file_path="entities/삼성전자.md",
                title="삼성전자",
                aliases=(),
                summary="반도체 기업",
                markdown="# 삼성전자",
                version=2,
                updated_at=now,
                role="seed",
            )
        ]

    monkeypatch.setattr(researcher, "wnav_002", fake_wnav_002)
    snapshot = {
        "query": "최근 삼성전자 관심",
        "wiki_version_id": "wiki-build-9",
        "pages": [
            {"document_version_id": "version-samsung", "role": "seed"}
        ],
        "relations": [],
        "sources": [
            {
                "wiki_document_version_id": "version-samsung",
                "source_document_id": "source-1",
                "source_document_version_id": "source-version-1",
                "source_type": "web_clipping",
                "title": "삼성전자 저장 글",
                "url": "https://example.com/samsung",
                "relation_type": "derived_from",
                "saved_at": now.isoformat(),
                "saved_at_source": "event_occurred_at",
                "stored_at": now.isoformat(),
                "published_at": None,
                "clipped_on": None,
            }
        ],
        "truncated": False,
    }

    packet = asyncio.run(
        load_navigation_snapshot_packet(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic="삼성전자",
            snapshot=snapshot,
        )
    )

    assert calls == [
        (connection, ("version-samsung",), "wiki-build-9")
    ]
    assert packet.pages[0].document_version_id == "version-samsung"
    assert packet.sources[0].saved_at == now
    assert packet.wiki_version_id == "wiki-build-9"


def test_retry_tools_do_not_expose_new_wiki_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """고정 Snapshot 재시도에서는 Reader가 Wiki 후보를 다시 고르지 않는다."""
    tools = build_research_tools(
        _FakeConnection(),  # type: ignore[arg-type]
        user_id="user-1",
        topic_intent="news",
        collector=DocumentCollector(),
        allow_wiki_navigation=False,
    )

    assert [tool.name for tool in tools] == ["search_pool"]


def test_merge_context_documents_renumbers_references_and_deduplicates() -> None:
    """키워드별 검색 결과를 합칠 때 참조 충돌과 같은 URL 중복을 제거한다."""
    shared = _document("G1", title="공통 기사", url="https://example.com/shared")
    merged = merge_context_documents(
        [shared, _document("P1", title="루트 Wiki")],
        [shared, _document("G1", title="연결 기사", url="https://example.com/neighbor")],
    )

    assert [document.reference for document in merged] == ["G1", "P1", "G2"]
    assert [document.title for document in merged] == [
        "공통 기사",
        "루트 Wiki",
        "연결 기사",
    ]


def test_merge_keeps_distinct_personal_wiki_versions_with_same_source_url() -> None:
    """같은 클리핑에서 파생된 서로 다른 Wiki 노드는 Version ID로 구분한다."""
    merged = merge_context_documents(
        [
            _document(
                "P1",
                title="폭염",
                namespace="user/user-1",
                url="https://example.com/weather",
            )
        ],
        [
            _document(
                "P2",
                title="태풍 돌핀",
                namespace="user/user-1",
                url="https://example.com/weather",
            )
        ],
    )

    assert [document.title for document in merged] == ["폭염", "태풍 돌핀"]
    assert [document.reference for document in merged] == ["P1", "P2"]


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

    assert list(tools) == ["wiki_search", "wiki_read", "search_pool"]


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


def test_planned_queries_search_bundle_before_llm_and_reuse_it_for_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """고정된 연결 키워드는 LLM 판단 전에 검색하고 한 번의 실시간 보강에 재사용한다."""
    queries = _patch_db(
        monkeypatch,
        [_document("G1", title="루트 기사", url="https://example.com/root")],
    )
    captured_live: list[list[str]] = []

    async def fake_loop(system_prompt, user_prompt, tools, **kwargs):
        """선계획 검색 뒤 추가 도구 호출 없이 조사를 끝낸다."""
        assert "이미 저장 자료 검색을 마쳤다" in user_prompt
        return ToolLoopResult(text="선계획 검색 완료", stop_reason="final")

    def fake_collect(topic, user_id, *, model, related_keywords):
        """실시간 보강에 전달된 연결 키워드를 기록한다."""
        captured_live.append(list(related_keywords))
        return []

    monkeypatch.setattr(researcher, "run_tool_loop", fake_loop)
    monkeypatch.setattr(researcher, "collect_live_context", fake_collect)

    outcome = asyncio.run(
        research_context(
            _FakeConnection(),  # type: ignore[arg-type]
            topic="생성형 AI",
            user_id="user-1",
            planned_queries=["AI 에이전트", "RAG", "ai 에이전트"],
        )
    )

    assert queries == ["생성형 AI", "AI 에이전트", "RAG"]
    assert captured_live == [["AI 에이전트", "RAG"]]
    assert outcome.collected_live is True


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
    assert "wiki_search" in researcher.SYSTEM_PROMPT
    assert "wiki_read" in researcher.SYSTEM_PROMPT
    assert "collect_live" not in researcher.SYSTEM_PROMPT


def test_personal_wiki_documents_do_not_count_toward_sufficiency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """개인 Wiki 문서는 실시간 수집 판정에서 세지 않는다.

    판정이 묻는 것은 "인터넷에 새로 나가야 하는가"다. 어제 저장한 Wiki 문서가
    있다고 오늘 소식이 필요 없어지지 않는다. (2026-08-05 실측: 무관한 주제에서
    Wiki 문서 5건이 잡혀 실시간 수집이 통째로 생략됐다.)
    """
    found = [
        _document(f"P{n}", title=f"위키 {n}", namespace="wiki", url=f"https://w/{n}")
        for n in range(1, 6)
    ]

    outcome, collected = _run_research(monkeypatch, found)

    assert collected == ["코스피"]
    # search_pool은 개인 Wiki를 반환하지 않는다. 개인 Wiki는 Navigator 도구로만
    # 읽으므로 이 실행에는 실시간 문서만 남는다.
    assert [document.title for document in outcome.documents] == [
        "새 기사",
    ]


def test_chunks_of_one_document_count_as_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """같은 문서의 청크 여러 건을 1건으로 센다.

    Wiki·풀 검색은 청크 단위로 반환하므로, 세지 않으면 문서 하나가 여러 건으로
    부풀어 기준(3건)을 넘겨버린다.
    """
    found = [
        ReportContextDocument(
            reference=f"G{n}",
            document_version_id="ver-same",
            chunk_id=f"chunk-{n}",
            namespace_key="global",
            title=f"조각 {n}",
            content="본문",
            url=f"https://example.com/{n}",
            score=0.9,
        )
        for n in range(1, 6)
    ]

    outcome, collected = _run_research(monkeypatch, found)

    assert collected == ["코스피"]
    assert len(outcome.documents) == 6


def test_search_drops_personal_documents_below_score_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """점수 하한에 못 미치는 개인 Wiki 문서는 근거에서 뺀다.

    Wiki 검색은 매칭이 없어도 문서를 채워 반환하되 점수를 0으로 남긴다. 거르지
    않으면 무관한 주제에서 목차 파일(Schema) 청크가 근거로 들어온다.
    """
    _patch_db(
        monkeypatch,
        [
            _document("P1", title="관련 문서", namespace="wiki", score=0.13),
            _document("P2", title="Schema", namespace="wiki", score=0.0),
        ],
    )
    # 이 검사는 개인 Wiki 컷오프만 본다. 풀 선별은 제 규칙대로 동작하게 둔다.
    monkeypatch.setattr(
        researcher,
        "select_pool_documents",
        lambda docs, **kwargs: [d for d in docs if d.namespace_key == "global"],
    )

    found = asyncio.run(
        researcher.search_stored_documents(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            query="코스피",
        )
    )

    assert [document.title for document in found] == ["관련 문서"]


def test_outcome_records_that_live_collection_was_attempted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실시간 수집을 시도했으면 결과에 표시한다.

    호출자(graph.load_context)가 같은 수집을 한 번 더 돌리지 않으려면 이 표식이
    필요하다. 성공 여부가 아니라 시도 여부다.
    """
    outcome, collected = _run_research(
        monkeypatch, [_document("G1", title="기사", url="https://example.com/a")]
    )

    assert collected == ["코스피"]
    assert outcome.collected_live is True


def test_outcome_marks_attempt_even_when_live_collection_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실시간 수집이 실패해도 '시도했다'로 남긴다.

    실패했다면 조건이 같으므로 고정 경로가 다시 불러도 대개 또 실패한다.
    """
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

    assert outcome.collected_live is True


def test_outcome_reports_no_attempt_when_pool_suffices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """창고가 충분하면 시도하지 않았다고 남긴다."""
    found = [
        _document(f"G{n}", title=f"기사 {n}", url=f"https://example.com/{n}")
        for n in range(1, 4)
    ]

    outcome, collected = _run_research(monkeypatch, found)

    assert collected == []
    assert outcome.collected_live is False
