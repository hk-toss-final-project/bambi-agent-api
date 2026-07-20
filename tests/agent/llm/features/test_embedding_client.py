"""공유 Embedding 경계의 캐시와 위임 동작을 검증한다."""

import pytest

from agent.llm.features import embedding_client


class _FakeEmbeddings:
    """호출 입력을 기록하고 고정 Vector를 반환하는 Client 대역."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """입력당 [1.0] Vector를 반환한다."""
        self.calls.append(texts)
        return [[1.0] for _ in texts]


def test_embed_texts_uses_cached_client_per_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(model, dimensions) 조합별 캐시 클라이언트로 위임한다."""
    fake = _FakeEmbeddings()
    monkeypatch.setitem(embedding_client._clients, ("test-model", 1536), fake)

    vectors = embedding_client.embed_texts(
        ["가", "나"], model="test-model", dimensions=1536
    )

    assert vectors == [[1.0], [1.0]]
    assert fake.calls == [["가", "나"]]
    assert (
        embedding_client.get_embedding_client("test-model", dimensions=1536) is fake
    )


def test_embed_texts_returns_empty_without_call() -> None:
    """빈 입력은 클라이언트 생성 없이 빈 목록을 반환한다."""
    assert embedding_client.embed_texts([], model="unused") == []
