"""LangGraph 오케스트레이션 그래프의 노드 순서와 결과 조립을 검증한다."""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from agent import graph as agent_graph


class _FakeConnection:
    """transaction 문맥만 제공하는 Connection Test Double."""

    def __init__(self) -> None:
        """Transaction 진입 횟수를 0으로 초기화한다."""
        self.transactions = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """열린 Transaction 수를 세는 문맥을 제공한다."""
        self.transactions += 1
        yield


def _fake_source() -> SimpleNamespace:
    """그래프 노드가 읽는 원본 Version 레코드 대역."""
    return SimpleNamespace(
        source_document_id="source-1",
        source_document_version_id="source-version-1",
        namespace_key="user/user-1",
        title="원본 제목",
        raw_content="# 본문",
        description="설명",
        tags=["tag"],
        canonical_url="https://example.com",
        content_hash="hash",
    )


def _fake_persisted() -> SimpleNamespace:
    """persist 노드가 반환하는 Build 결과 대역."""
    document = SimpleNamespace(
        document_id="doc-1",
        document_version_id="doc-version-1",
        document_kind="entity",
        document_key="entity-key",
        file_path="entities/entity-key.md",
        version=1,
        action="created",
    )
    return SimpleNamespace(
        wiki_version_id="wiki-version-1",
        wiki_version=3,
        chunk_count=2,
        stored_relation_count=4,
        affected_documents=[document],
    )


def test_run_personal_wiki_build_assembles_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wiki 그래프가 조회→분류→계획→저장→임베딩 순서로 결과를 조립한다."""
    order: list[str] = []
    plan = SimpleNamespace(
        index=SimpleNamespace(content="index"),
        source_manifest=SimpleNamespace(content="manifest"),
        log_entry=SimpleNamespace(content="log"),
        extracted_relation_count=2,
        isolated_node_count=1,
        relation_warnings=["관계 경고"],
    )

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """테스트에서 DB 사용자 Scope 설정을 생략한다."""
        return None

    async def fake_get_source(connection: Any, **kwargs: Any) -> SimpleNamespace:
        """원본 조회 순서를 기록하고 고정 원본을 반환한다."""
        order.append("load_source")
        return _fake_source()

    async def fake_entries(connection: Any, **kwargs: Any) -> list[object]:
        """기존 Wiki 문서가 없는 상태를 반환한다."""
        return []

    async def fake_relations(connection: Any, **kwargs: Any) -> list[object]:
        """기존 Wiki 관계가 없는 상태를 반환한다."""
        return []

    def fake_classify(**kwargs: Any) -> str:
        """분류 입력을 검증하고 고정 분류 결과를 반환한다."""
        order.append("classify")
        assert kwargs["source_title"] == "원본 제목"
        assert kwargs["model"] == "test-model"
        return "classification"

    async def fake_wba_003(**kwargs: Any) -> SimpleNamespace:
        """WBA-003 계획 함수 호출을 기록하고 고정 계획을 반환한다."""
        order.append("plan")
        assert kwargs["classification"] == "classification"
        return plan

    async def fake_pwiki_002(
        connection: Any, **kwargs: Any
    ) -> SimpleNamespace:
        """PWIKI-002 facade 호출을 기록하고 저장 결과를 반환한다."""
        order.append("persist")
        assert kwargs["plan"] is plan
        assert kwargs["job_id"] == "job-1"
        return _fake_persisted()

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        agent_graph, "get_user_source_document_version_for_agent", fake_get_source
    )
    monkeypatch.setattr(agent_graph, "list_existing_wiki_entries", fake_entries)
    monkeypatch.setattr(agent_graph, "list_existing_wiki_relations", fake_relations)
    monkeypatch.setattr(agent_graph, "classify_source_for_wiki", fake_classify)
    monkeypatch.setattr(agent_graph, "wba_003", fake_wba_003)
    monkeypatch.setattr(agent_graph, "pwiki_002", fake_pwiki_002)

    connection = _FakeConnection()
    result = asyncio.run(
        agent_graph.run_personal_wiki_build(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_version_id="source-version-1",
            job_id="job-1",
            model="test-model",
        )
    )

    assert order == ["load_source", "classify", "plan", "persist"]
    assert result["source_document_id"] == "source-1"
    assert result["wiki_version_id"] == "wiki-version-1"
    assert result["chunk_count"] == 2
    assert result["extracted_relation_count"] == 2
    assert result["stored_relation_count"] == 4
    assert result["isolated_node_count"] == 1
    assert result["relation_warnings"] == ["관계 경고"]
    assert "embedding_count" not in result
    assert result["affected_documents"][0]["document_key"] == "entity-key"
    assert result["artifacts"]["index"] == "index"


def test_run_report_generation_chains_search_generate_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report Builder 그래프가 검색→생성→영속화 순서로 저장 결과를 반환한다."""
    order: list[str] = []

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """테스트에서 DB 사용자 Scope 설정을 생략한다."""
        return None

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[str]:
        """PRAG-003 검색 호출을 기록하고 고정 Context를 반환한다."""
        order.append("load_context")
        assert kwargs["query"] == "개인화"
        return ["context-1"]

    async def fake_prag_006(contexts: list[str]) -> list[str]:
        """검색 Context를 변경 없이 반환한다."""
        return contexts

    def fake_collect_live_context(topic: str, user_id: str, *, model: str = "") -> list:
        """실시간 수집(뉴스·YouTube·Reddit + LLM)을 대체한다.

        대체하지 않으면 이 테스트가 실제 네트워크와 OpenAI를 호출한다.
        """
        order.append("collect_live")
        assert topic == "개인화"
        return []

    def fake_generate(**kwargs: Any) -> str:
        """생성 입력을 검증하고 고정 콘텐츠를 반환한다."""
        order.append("generate")
        assert kwargs["contexts"] == ["context-1"]
        assert kwargs["language"] == "ko"
        return "generated"

    async def fake_prag_007(connection: Any, **kwargs: Any) -> dict[str, object]:
        """PRAG-007 저장 호출을 기록하고 고정 결과를 반환한다."""
        order.append("persist")
        assert kwargs["generated"] == "generated"
        assert kwargs["attempt_number"] == 2
        assert kwargs["latency_ms"] >= 0
        return {"content_candidate_id": "candidate-1"}

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "prag_003", fake_prag_003)
    monkeypatch.setattr(agent_graph, "prag_006", fake_prag_006)
    monkeypatch.setattr(agent_graph, "generate_report_content", fake_generate)
    monkeypatch.setattr(agent_graph, "collect_live_context", fake_collect_live_context)
    monkeypatch.setattr(agent_graph, "prag_007", fake_prag_007)

    connection = _FakeConnection()
    result = asyncio.run(
        agent_graph.run_report_generation(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=2,
            topic="개인화",
            content_type="article",
            language="ko",
            model="test-model",
        )
    )

    # 실시간 수집(REPORT-005)이 개인 Wiki 검색과 생성 사이에 들어간다.
    assert order == ["load_context", "collect_live", "generate", "persist"]
    assert result == {"content_candidate_id": "candidate-1"}
    assert connection.transactions == 2
