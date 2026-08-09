"""Report Builder Wiki Query Embedding과 Keyword 폴백을 검증한다."""

from agent.report_builder.features import wiki_retrieval


def test_embed_wiki_queries_batches_and_validates_vectors(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """중복 Query는 한 번만 호출하고 정확한 1536차원 Vector만 반환한다."""
    captured: dict[str, object] = {}

    def fake_embed(texts, *, model, dimensions):  # type: ignore[no-untyped-def]
        """Embedding 호출 인자와 고정 Vector를 반환한다."""
        captured.update(texts=texts, model=model, dimensions=dimensions)
        return [[0.1] * dimensions for _text in texts]

    monkeypatch.setattr(wiki_retrieval, "embed_texts", fake_embed)

    result = wiki_retrieval.embed_wiki_queries(["날씨", "날씨", " 폭염 "])

    assert captured == {
        "texts": ["날씨", "폭염"],
        "model": "text-embedding-3-small",
        "dimensions": 1536,
    }
    assert set(result) == {"날씨", "폭염"}
    assert len(result["날씨"]) == 1536


def test_embed_wiki_queries_falls_back_on_provider_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Embedding Provider 장애는 예외 대신 빈 결과로 격리한다."""

    def fail_embed(*args, **kwargs):  # type: ignore[no-untyped-def]
        """외부 Provider 장애를 재현한다."""
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(wiki_retrieval, "embed_texts", fail_embed)

    assert wiki_retrieval.embed_wiki_queries(["날씨"]) == {}
