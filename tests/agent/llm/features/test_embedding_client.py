"""공유 Embedding 경계의 캐시와 위임 동작을 검증한다."""

import pytest

from agent.llm.features import client as llm_client
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


def test_retrying_embedding_client_records_usage_and_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embedding 실패·성공 시도와 성공 응답의 실제 입력 Token을 수집한다."""

    class _TransientError(RuntimeError):
        """테스트용 Embedding 일시 오류."""

    calls = 0

    def embed(texts: list[str]) -> embedding_client._EmbeddingCallResult:
        """첫 호출은 실패하고 다음 호출은 Vector·Token을 반환한다."""
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _TransientError("일시 실패")
        return embedding_client._EmbeddingCallResult(
            vectors=[[0.1], [0.2]],
            input_tokens=17,
            response_metadata={"headers": {"x-request-id": "emb-req"}},
        )

    monkeypatch.setattr(
        llm_client,
        "_transient_error_types",
        lambda: (_TransientError,),
    )
    monkeypatch.setattr(llm_client, "_BACKOFF_BASE_SECONDS", 0)
    client = embedding_client._RetryingEmbeddingClient("embedding-model", embed)

    with llm_client.capture_llm_calls() as captured:
        vectors = client.embed_documents(["가", "나"])

    assert vectors == [[0.1], [0.2]]
    assert [item.status for item in captured] == ["failed", "succeeded"]
    assert all(item.operation == "embedding" for item in captured)
    assert captured[1].input_tokens == 17
    assert captured[1].request_id == "emb-req"
    assert captured[1].metadata == {"input_count": 2}
