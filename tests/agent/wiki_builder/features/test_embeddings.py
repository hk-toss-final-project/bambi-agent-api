"""개인 Wiki Chunk Embedding Provider 경계를 검증한다."""

import pytest

from agent.wiki_builder.features.embeddings import generate_wiki_embeddings
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
