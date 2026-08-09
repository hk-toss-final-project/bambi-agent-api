"""개인 Wiki Hybrid 검색의 RRF 결합과 Keyword 폴백을 검증한다."""

import asyncio
from typing import Any

from domain.personal_wiki.retrieval.features import hybrid
from shared.report_models import ReportContextDocument


def _document(
    name: str, *, namespace: str = "user/user-1", score: float = 0.5
) -> ReportContextDocument:
    """Hybrid 검색 테스트용 Context Chunk를 만든다."""
    prefix = "G" if namespace == "global" else "P"
    return ReportContextDocument(
        reference=f"{prefix}-{name}",
        document_version_id=f"version-{name}",
        chunk_id=f"chunk-{name}",
        namespace_key=namespace,
        title=name,
        content=f"{name} 본문",
        url=None,
        score=score,
    )


def test_prag_003_fuses_personal_rankings_and_preserves_global_results(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    """개인 Wiki만 RRF로 결합하고 Global Keyword 순서는 뒤에 유지한다."""
    captured: dict[str, Any] = {}

    async def fake_keyword(*args, **kwargs):  # type: ignore[no-untyped-def]
        """개인 두 건과 Global 한 건의 Keyword 결과를 반환한다."""
        return [
            _document("A", score=0.7),
            _document("B", score=0.6),
            _document("news", namespace="global", score=1.1),
        ]

    async def fake_vector(*args, **kwargs):  # type: ignore[no-untyped-def]
        """Keyword와 겹치는 B 및 Vector 전용 C를 반환한다."""
        captured.update(kwargs)
        return [_document("B", score=0.9), _document("C", score=0.8)]

    monkeypatch.setattr(hybrid, "prag_001", fake_keyword)
    monkeypatch.setattr(hybrid, "prag_002", fake_vector)

    result = asyncio.run(
        hybrid.prag_003(
            object(),  # type: ignore[arg-type]
            user_id="user-1",
            query="날씨",
            top_k_per_scope=3,
            query_embedding=[0.1] * 1536,
        )
    )

    assert [document.title for document in result] == ["B", "A", "C", "news"]
    assert len(captured["query_embedding"]) == 1536
    assert captured["model_name"] == "text-embedding-3-small"


def test_prag_003_falls_back_to_keyword_when_vector_query_fails(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Vector 저장소 장애는 리포트 검색 전체를 실패시키지 않는다."""

    async def fake_keyword(*args, **kwargs):  # type: ignore[no-untyped-def]
        """Keyword 개인·Global 결과를 반환한다."""
        return [
            _document("A", score=0.7),
            _document("news", namespace="global", score=1.1),
        ]

    async def fail_vector(*args, **kwargs):  # type: ignore[no-untyped-def]
        """pgvector 조회 장애를 재현한다."""
        raise RuntimeError("vector unavailable")

    monkeypatch.setattr(hybrid, "prag_001", fake_keyword)
    monkeypatch.setattr(hybrid, "prag_002", fail_vector)

    result = asyncio.run(
        hybrid.prag_003(
            object(),  # type: ignore[arg-type]
            user_id="user-1",
            query="날씨",
            query_embedding=[0.1] * 1536,
        )
    )

    assert [document.title for document in result] == ["A", "news"]
