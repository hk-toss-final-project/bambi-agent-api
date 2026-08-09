"""개인 Wiki Keyword·Vector RRF 재정렬을 검증한다."""

import asyncio

import pytest

from domain.personal_wiki.retrieval.api import prag_004
from shared.report_models import ReportContextDocument


def _document(name: str, *, score: float) -> ReportContextDocument:
    """RRF 테스트용 개인 Wiki Chunk를 만든다."""
    return ReportContextDocument(
        reference=f"P-{name}",
        document_version_id=f"version-{name}",
        chunk_id=f"chunk-{name}",
        namespace_key="user/user-1",
        title=name,
        content=f"{name} 본문",
        url=None,
        score=score,
    )


def test_prag_004_prioritizes_candidate_found_by_both_rankings() -> None:
    """Keyword와 Vector 양쪽에 등장한 Chunk를 단일 결과로 가장 먼저 둔다."""
    keyword = [_document("A", score=0.7), _document("B", score=0.6)]
    vector = [_document("B", score=0.9), _document("C", score=0.8)]

    result = asyncio.run(prag_004(keyword, vector, top_k=3))

    assert [document.title for document in result] == ["B", "A", "C"]
    assert result[0].score == 0.9
    assert len({document.chunk_id for document in result}) == 3


def test_prag_004_validates_cost_bounds() -> None:
    """잘못된 결과 상한과 RRF 상수는 후보 계산 전에 거절한다."""
    with pytest.raises(ValueError, match="top_k"):
        asyncio.run(prag_004([], top_k=0))
    with pytest.raises(ValueError, match="rrf_k"):
        asyncio.run(prag_004([], rrf_k=0))
