"""개인 Wiki Vector Search 기능 경계를 검증한다."""

import asyncio

import pytest

from domain.personal_wiki.retrieval.features import vector


def test_prag_002_delegates_validated_vector_to_persistence(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """1536차원 Query와 모델·상한을 영속화 facade에 전달한다."""
    captured: dict[str, object] = {}

    async def fake_load(*args, **kwargs):  # type: ignore[no-untyped-def]
        """Vector 저장소 호출 인자를 기록한다."""
        captured.update(kwargs)
        return []

    monkeypatch.setattr(vector, "load_personal_wiki_vector_context", fake_load)

    result = asyncio.run(
        vector.prag_002(
            object(),  # type: ignore[arg-type]
            user_id="user-1",
            query_embedding=[0.1] * 1536,
            top_k=7,
        )
    )

    assert result == []
    assert captured["user_id"] == "user-1"
    assert captured["model_name"] == "text-embedding-3-small"
    assert captured["top_k"] == 7


def test_prag_002_rejects_incompatible_vector_dimension() -> None:
    """저장 Embedding과 차원이 다른 Query는 DB 호출 전에 거절한다."""
    with pytest.raises(ValueError, match="1536차원"):
        asyncio.run(
            vector.prag_002(
                object(),  # type: ignore[arg-type]
                user_id="user-1",
                query_embedding=[0.1],
            )
        )
