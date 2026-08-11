"""LangGraph Wiki 읽기 루프 V2의 Seed 선택·분기·버전 호환성을 검증한다."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from agent.report_builder.features import read_loop
from agent.report_builder.features.read_loop import (
    build_wiki_read_graph_v2,
    research_context_for_version,
    run_wiki_read_graph_v2,
    select_wiki_seed_candidates,
)
from agent.report_builder.features.researcher import ResearchOutcome
from shared.report_models import ReportContextDocument
from shared.wiki_navigation_models import (
    WikiNavigationCandidate,
    WikiNavigationPacket,
)


def _candidate(
    version_id: str,
    title: str,
    summary: str,
    *,
    exact: bool = False,
    alias: bool = False,
    keyword_rank: int | None = None,
    vector_rank: int | None = None,
    rrf_score: float = 0.0,
) -> WikiNavigationCandidate:
    """결정적 Seed 선택 테스트용 Wiki 후보를 만든다."""
    return WikiNavigationCandidate(
        document_id=f"doc-{version_id}",
        document_version_id=version_id,
        document_kind="concept",
        document_key=version_id,
        file_path=f"concepts/{version_id}.md",
        title=title,
        aliases=(),
        summary=summary,
        updated_at=datetime(2026, 8, 11, tzinfo=UTC),
        exact_match=exact,
        alias_match=alias,
        keyword_rank=keyword_rank,
        vector_rank=vector_rank,
        rrf_score=rrf_score,
    )


def _document(reference: str, *, namespace: str = "global") -> ReportContextDocument:
    """읽기 루프가 합칠 테스트용 근거 문서를 만든다."""
    return ReportContextDocument(
        reference=reference,
        document_version_id=f"version-{reference}",
        chunk_id=f"chunk-{reference}",
        namespace_key=namespace,
        title=f"근거 {reference}",
        content=f"근거 {reference} 본문",
        url=f"https://example.com/{reference}" if namespace == "global" else None,
        score=0.9,
    )


def _packet() -> WikiNavigationPacket:
    """DB 조회를 대체할 최소 Wiki Navigation Packet을 만든다."""
    return WikiNavigationPacket(
        query="AI 에이전트",
        wiki_version_id="wiki-1",
        candidates=(),
        pages=(),
        relations=(),
        sources=(),
        trace=(),
    )


def test_select_wiki_seed_candidates_prefers_question_relevance_over_rrf() -> None:
    """높은 RRF의 무관 후보보다 질문에 직접 언급된 Page를 먼저 선택한다."""
    candidates = [
        _candidate(
            "database",
            "DBeaver",
            "데이터베이스 관리 도구",
            keyword_rank=1,
            rrf_score=0.9,
        ),
        _candidate(
            "agents",
            "AI 에이전트",
            "도구 사용과 계획 실행",
            exact=True,
            keyword_rank=30,
            rrf_score=0.01,
        ),
        _candidate(
            "rag",
            "RAG",
            "에이전트의 지식 검색 방식",
            keyword_rank=2,
            rrf_score=0.3,
        ),
    ]

    selected = select_wiki_seed_candidates(
        "내 Wiki에서 AI 에이전트와 RAG의 관계를 설명해줘", candidates
    )

    assert [candidate.document_version_id for candidate in selected] == [
        "agents",
        "rag",
    ]


def test_wiki_read_v2_graph_exposes_explicit_pipeline_nodes() -> None:
    """V2 그래프가 읽기·판정·Live 보강 단계를 독립 노드로 드러낸다."""
    nodes = set(build_wiki_read_graph_v2().get_graph().nodes)

    assert nodes == {
        "__start__",
        "restore_or_locate",
        "select_seed",
        "navigate",
        "search_global",
        "assess",
        "collect_live",
        "finalize",
        "__end__",
    }


def test_v2_restores_snapshot_and_skips_live_when_pool_is_sufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """재시도 Snapshot은 새 Locate 없이 복원하고 충분한 Global 근거면 Live를 생략한다."""
    packet = _packet()
    calls: list[str] = []

    async def fake_restore(*args: Any, **kwargs: Any) -> WikiNavigationPacket:
        """고정 Packet 복원 호출을 기록한다."""
        calls.append("restore")
        return packet

    async def fake_global(*args: Any, **kwargs: Any) -> list[ReportContextDocument]:
        """충분하다고 판정할 Global 근거를 반환한다."""
        calls.append("global")
        return [_document("G1")]

    async def unexpected_locate(*args: Any, **kwargs: Any) -> list[Any]:
        """Snapshot 경로에서 Locate가 호출되면 테스트를 실패시킨다."""
        raise AssertionError("Snapshot 재시도에서 Locate를 호출하면 안 됩니다.")

    monkeypatch.setattr(read_loop, "load_navigation_snapshot_packet", fake_restore)
    monkeypatch.setattr(read_loop, "search_global_documents", fake_global)
    monkeypatch.setattr(read_loop, "wnav_001", unexpected_locate)
    monkeypatch.setattr(
        read_loop,
        "navigation_packet_documents",
        lambda packet, **kwargs: [_document("P1", namespace="user/user-1")],
    )
    monkeypatch.setattr(read_loop, "is_pool_sufficient", lambda documents: True)
    monkeypatch.setattr(read_loop, "is_pool_relevant", lambda topic, documents: True)
    monkeypatch.setattr(
        read_loop,
        "collect_live_context",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("충분한 근거에서 Live를 호출하면 안 됩니다.")
        ),
    )

    outcome = asyncio.run(
        run_wiki_read_graph_v2(
            object(),  # type: ignore[arg-type]
            topic="AI 에이전트",
            user_id="user-1",
            wiki_version_id="wiki-1",
            navigation_snapshot={"packet": "fixed"},
        )
    )

    assert calls == ["restore", "global"]
    assert outcome.collected_live is False
    assert {document.namespace_key for document in outcome.documents} == {
        "user/user-1",
        "global",
    }
    assert outcome.stop_reason == "langgraph_v2"


def test_v2_locates_navigates_collects_live_and_persists_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """신규 실행은 Seed를 읽고 부족한 Global 근거를 Live로 보강한 뒤 Snapshot을 저장한다."""
    packet = _packet()
    candidate = _candidate(
        "agents",
        "AI 에이전트",
        "도구 사용과 계획 실행",
        exact=True,
    )
    captured: dict[str, Any] = {}

    async def fake_locate(*args: Any, **kwargs: Any) -> list[WikiNavigationCandidate]:
        """질문과 정확히 맞는 후보 하나를 반환한다."""
        return [candidate]

    async def fake_navigate(*args: Any, **kwargs: Any) -> WikiNavigationPacket:
        """선택된 Version ID를 기록하고 Packet을 반환한다."""
        captured["selected"] = kwargs["selected_document_version_ids"]
        return packet

    async def fake_global(*args: Any, **kwargs: Any) -> list[ReportContextDocument]:
        """부족 판정을 유도할 Global 근거 한 건을 반환한다."""
        return [_document("G1")]

    async def fake_persist(*args: Any, **kwargs: Any) -> None:
        """첫 실행의 Navigation Snapshot 저장 인자를 기록한다."""
        captured["persist"] = kwargs

    monkeypatch.setattr(read_loop, "embed_wiki_queries", lambda queries: {})
    monkeypatch.setattr(read_loop, "wnav_001", fake_locate)
    monkeypatch.setattr(read_loop, "wnav_006", fake_navigate)
    monkeypatch.setattr(read_loop, "search_global_documents", fake_global)
    monkeypatch.setattr(
        read_loop,
        "navigation_packet_documents",
        lambda packet, **kwargs: [_document("P1", namespace="user/user-1")],
    )
    monkeypatch.setattr(read_loop, "is_pool_sufficient", lambda documents: False)
    monkeypatch.setattr(read_loop, "is_pool_relevant", lambda topic, documents: True)
    monkeypatch.setattr(
        read_loop, "collect_live_context", lambda *args, **kwargs: [_document("L1")]
    )
    monkeypatch.setattr(read_loop, "persist_report_navigation_snapshot", fake_persist)

    outcome = asyncio.run(
        run_wiki_read_graph_v2(
            object(),  # type: ignore[arg-type]
            topic="AI 에이전트",
            user_id="user-1",
            wiki_version_id="wiki-1",
            job_id="job-1",
        )
    )

    assert captured["selected"] == ["agents"]
    assert captured["persist"]["job_id"] == "job-1"
    assert outcome.collected_live is True
    assert len(outcome.documents) == 3
    assert [stat[0] for stat in outcome.tool_stats] == [
        "restore_or_locate",
        "select_seed",
        "navigate",
        "search_global",
        "assess",
        "collect_live",
        "finalize",
    ]


def test_research_context_for_version_routes_legacy_and_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """버전 어댑터가 V1을 기본으로 보존하고 V2만 새 그래프로 보낸다."""
    calls: list[str] = []

    async def fake_legacy(*args: Any, **kwargs: Any) -> ResearchOutcome:
        """V1 호출을 기록한다."""
        calls.append("legacy")
        return ResearchOutcome(stop_reason="legacy")

    async def fake_v2(*args: Any, **kwargs: Any) -> ResearchOutcome:
        """V2 호출을 기록한다."""
        calls.append("v2")
        return ResearchOutcome(stop_reason="v2")

    monkeypatch.setattr(read_loop, "research_context", fake_legacy)
    monkeypatch.setattr(read_loop, "run_wiki_read_graph_v2", fake_v2)

    legacy = asyncio.run(
        research_context_for_version(
            object(),  # type: ignore[arg-type]
            topic="주제",
            user_id="user-1",
        )
    )
    v2 = asyncio.run(
        research_context_for_version(
            object(),  # type: ignore[arg-type]
            pipeline_version="langgraph_v2",
            topic="주제",
            user_id="user-1",
        )
    )

    assert calls == ["legacy", "v2"]
    assert legacy.stop_reason == "legacy"
    assert v2.stop_reason == "v2"


def test_research_context_for_version_rejects_unknown_version() -> None:
    """잘못된 Job 버전은 조용히 다른 실행기로 폴백하지 않는다."""
    with pytest.raises(ValueError, match="지원하지 않는"):
        asyncio.run(
            research_context_for_version(
                object(),  # type: ignore[arg-type]
                pipeline_version="v3",
                topic="주제",
                user_id="user-1",
            )
        )
