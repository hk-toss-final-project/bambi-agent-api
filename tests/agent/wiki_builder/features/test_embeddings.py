"""개인 Wiki Chunk Embedding Provider 경계를 검증한다."""

import asyncio
from contextlib import AbstractAsyncContextManager
from typing import Any

import pytest

from agent.wiki_builder.features import embeddings as wiki_embeddings
from agent.wiki_builder.features.embeddings import (
    generate_relation_query_embeddings,
    generate_wiki_embeddings,
)
from infrastructure.persistence.features.personal_wiki import WikiChunkForEmbedding


class _FakeClient:
    """고정된 Vector를 반환하는 Embedding Client Test Double."""

    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = vectors
        self.texts: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """입력 문자열을 기록하고 고정 Vector를 반환한다."""
        self.texts = texts
        return self.vectors


def test_generate_wiki_embeddings_keeps_chunk_identity() -> None:
    """Provider Vector를 원래 Chunk ID·본문과 같은 순서로 결합한다."""
    client = _FakeClient([[0.1] * 1536, [0.2] * 1536])
    chunks = [
        WikiChunkForEmbedding("chunk-1", "첫 번째"),
        WikiChunkForEmbedding("chunk-2", "두 번째"),
    ]

    result = generate_wiki_embeddings(
        chunks,
        client_factory=lambda model: client,
    )

    assert client.texts == ["첫 번째", "두 번째"]
    assert result[0].chunk_id == "chunk-1"
    assert result[1].embedding == [0.2] * 1536


def test_generate_wiki_embeddings_rejects_missing_vectors() -> None:
    """Provider가 Chunk 수와 다른 Vector 수를 반환하면 실패한다."""
    chunks = [WikiChunkForEmbedding("chunk-1", "본문")]

    with pytest.raises(RuntimeError, match="Vector 개수"):
        generate_wiki_embeddings(
            chunks,
            client_factory=lambda model: _FakeClient([]),
        )


def test_generate_relation_query_embeddings_preserves_query_order() -> None:
    """관계 후보 Query Vector를 입력 노드 순서대로 반환한다."""
    client = _FakeClient([[1.0, 0.0], [0.0, 1.0]])

    result = generate_relation_query_embeddings(
        ["폭염", "태풍 돌핀"],
        client_factory=lambda _model: client,
    )

    assert client.texts == ["폭염", "태풍 돌핀"]
    assert result == [(1.0, 0.0), (0.0, 1.0)]


class _Transaction(AbstractAsyncContextManager[None]):
    """WBA-011의 짧은 조회·저장 Transaction을 흉내 낸다."""

    async def __aenter__(self) -> None:
        """Transaction 경계에 진입한다."""

    async def __aexit__(self, *args: Any) -> None:
        """Transaction 경계에서 나온다."""


class _Connection:
    """테스트용 Transaction 팩토리만 제공한다."""

    def transaction(self) -> _Transaction:
        """빈 비동기 Transaction 경계를 반환한다."""
        return _Transaction()


def test_wba_011_reads_then_persists_embeddings_without_open_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider 호출 전후로 DB Transaction을 나누어 Embedding을 저장한다."""
    scopes: list[str] = []
    persisted: list[object] = []

    async def fake_scope(_connection: object, *, user_id: str) -> None:
        """설정한 RLS 사용자를 기록한다."""
        scopes.append(user_id)

    async def fake_chunks(
        _connection: object,
        *,
        namespace_key: str,
        document_version_ids: list[str],
    ) -> list[WikiChunkForEmbedding]:
        """재임베딩할 Chunk 하나를 반환한다."""
        assert namespace_key == "user/56"
        assert document_version_ids == ["version-1"]
        return [WikiChunkForEmbedding("chunk-1", "폭염")]

    async def fake_persist(
        _connection: object,
        *,
        namespace_key: str,
        model_name: str,
        values: list[object],
    ) -> int:
        """저장 값을 기록하고 건수를 반환한다."""
        persisted.extend(values)
        assert namespace_key == "user/56"
        assert model_name == "embed-test"
        return len(values)

    monkeypatch.setattr(wiki_embeddings, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(wiki_embeddings, "get_wiki_chunks_for_embedding", fake_chunks)
    monkeypatch.setattr(wiki_embeddings, "persist_wiki_embeddings", fake_persist)

    count = asyncio.run(
        wiki_embeddings.wba_011(
            _Connection(),  # type: ignore[arg-type]
            namespace_key="user/56",
            document_version_ids=["version-1"],
            model="embed-test",
            client_factory=lambda _model: _FakeClient([[0.1] * 1536]),
        )
    )

    assert count == 1
    assert scopes == ["56", "56"]
    assert len(persisted) == 1
