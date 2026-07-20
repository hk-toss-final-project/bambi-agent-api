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
    )

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        return None

    async def fake_get_source(connection: Any, **kwargs: Any) -> SimpleNamespace:
        order.append("load_source")
        return _fake_source()

    async def fake_entries(connection: Any, **kwargs: Any) -> list[object]:
        return []

    async def fake_relations(connection: Any, **kwargs: Any) -> list[object]:
        return []

    def fake_classify(**kwargs: Any) -> str:
        order.append("classify")
        assert kwargs["source_title"] == "원본 제목"
        assert kwargs["model"] == "test-model"
        return "classification"

    def fake_plan(**kwargs: Any) -> SimpleNamespace:
        order.append("plan")
        assert kwargs["classification"] == "classification"
        return plan

    async def fake_persist(connection: Any, **kwargs: Any) -> SimpleNamespace:
        order.append("persist")
        assert kwargs["plan"] is plan
        assert kwargs["job_id"] == "job-1"
        return _fake_persisted()

    async def fake_chunks(connection: Any, **kwargs: Any) -> list[str]:
        order.append("embed")
        assert kwargs["document_version_ids"] == ["doc-version-1"]
        return ["chunk"]

    def fake_embeddings(chunks: list[str], *, model: str) -> list[str]:
        assert model == "embed-model"
        return ["vector"]

    async def fake_persist_embeddings(connection: Any, **kwargs: Any) -> int:
        assert kwargs["model_name"] == "embed-model"
        return 1

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        agent_graph, "get_user_source_document_version_for_agent", fake_get_source
    )
    monkeypatch.setattr(agent_graph, "list_existing_wiki_entries", fake_entries)
    monkeypatch.setattr(agent_graph, "list_existing_wiki_relations", fake_relations)
    monkeypatch.setattr(agent_graph, "classify_source_for_wiki", fake_classify)
    monkeypatch.setattr(agent_graph, "build_wiki_plan", fake_plan)
    monkeypatch.setattr(agent_graph, "persist_wiki_build", fake_persist)
    monkeypatch.setattr(agent_graph, "get_wiki_chunks_for_embedding", fake_chunks)
    monkeypatch.setattr(agent_graph, "generate_wiki_embeddings", fake_embeddings)
    monkeypatch.setattr(
        agent_graph, "persist_wiki_embeddings", fake_persist_embeddings
    )

    connection = _FakeConnection()
    result = asyncio.run(
        agent_graph.run_personal_wiki_build(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_version_id="source-version-1",
            job_id="job-1",
            model="test-model",
            embedding_model="embed-model",
        )
    )

    assert order == ["load_source", "classify", "plan", "persist", "embed"]
    assert result["source_document_id"] == "source-1"
    assert result["wiki_version_id"] == "wiki-version-1"
    assert result["chunk_count"] == 2
    assert result["embedding_count"] == 1
    assert result["embedding_status"] == "completed"
    assert result["affected_documents"][0]["document_key"] == "entity-key"
    assert result["artifacts"]["index"] == "index"


def test_run_bambi_generation_chains_search_generate_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bambi 그래프가 검색→생성→영속화 순서로 저장 결과를 반환한다."""
    order: list[str] = []

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        return None

    async def fake_load_context(connection: Any, **kwargs: Any) -> list[str]:
        order.append("load_context")
        assert kwargs["query"] == "개인화"
        return ["context-1"]

    def fake_generate(**kwargs: Any) -> str:
        order.append("generate")
        assert kwargs["contexts"] == ["context-1"]
        assert kwargs["language"] == "ko"
        return "generated"

    async def fake_persist(connection: Any, **kwargs: Any) -> dict[str, object]:
        order.append("persist")
        assert kwargs["generated"] == "generated"
        assert kwargs["attempt_number"] == 2
        assert kwargs["latency_ms"] >= 0
        return {"content_candidate_id": "candidate-1"}

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "load_bambi_context", fake_load_context)
    monkeypatch.setattr(agent_graph, "generate_bambi_content", fake_generate)
    monkeypatch.setattr(agent_graph, "persist_bambi_generation", fake_persist)

    connection = _FakeConnection()
    result = asyncio.run(
        agent_graph.run_bambi_generation(
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

    assert order == ["load_context", "generate", "persist"]
    assert result == {"content_candidate_id": "candidate-1"}
    assert connection.transactions == 2
