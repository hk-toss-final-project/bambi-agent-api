"""Keyword·Vector 개인 Wiki 후보의 결정적 RRF 재정렬 기능."""

from collections.abc import Sequence
from dataclasses import replace

from shared.report_models import ReportContextDocument


def _context_key(document: ReportContextDocument) -> str:
    """RRF 중복 제거에 사용할 Scope 내 Chunk 식별 키를 반환한다."""
    stable_id = (
        document.chunk_id
        or document.document_version_id
        or document.url
        or document.reference
    )
    return f"{document.namespace_key}:{stable_id}"


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def prag_004(
    *ranked_groups: Sequence[ReportContextDocument],
    top_k: int = 5,
    rrf_k: int = 60,
) -> list[ReportContextDocument]:
    """[PRAG-004] 검색 결과 Reranking.

    Keyword·Vector 순위에 Reciprocal Rank Fusion을 적용해 개인 Wiki 후보를
    재정렬한다. 원래 검색 점수는 하류 품질 하한에 쓰이므로 최댓값을 보존한다.
    """
    if not 1 <= top_k <= 20:
        raise ValueError("PRAG-004 top_k는 1에서 20 사이여야 합니다.")
    if rrf_k < 1:
        raise ValueError("PRAG-004 rrf_k는 1 이상이어야 합니다.")
    documents: dict[str, ReportContextDocument] = {}
    original_scores: dict[str, float] = {}
    fused_scores: dict[str, float] = {}
    for group in ranked_groups:
        seen_in_group: set[str] = set()
        for rank, document in enumerate(group, start=1):
            key = _context_key(document)
            if key in seen_in_group:
                continue
            seen_in_group.add(key)
            documents.setdefault(key, document)
            original_scores[key] = max(
                original_scores.get(key, float("-inf")),
                float(document.score),
            )
            fused_scores[key] = fused_scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
    ordered_keys = sorted(
        documents,
        key=lambda key: (
            -fused_scores[key],
            -original_scores[key],
            key,
        ),
    )
    return [
        replace(documents[key], score=original_scores[key])
        for key in ordered_keys[:top_k]
    ]
