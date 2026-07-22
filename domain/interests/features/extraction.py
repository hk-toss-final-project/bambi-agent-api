"""개인 Wiki 문서에서 관심 키워드를 추출하는 기능 구현.

INT-001의 실제 구현 위치다. LLM 호출 없이 현재 Wiki 문서의 제목, 영역,
별칭, 태그와 요약을 결합해 결정적인 관심 후보와 근거 문서 목록을 만든다.
"""

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence

from shared.wiki_models import InterestCandidate

_TOKEN_PATTERN = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9._+-]{2,}")
_STOP_WORDS = {
    "관련",
    "내용",
    "문서",
    "설명",
    "개념",
    "정보",
    "대한",
    "위한",
    "통해",
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "other",
    "schema",
}


def _tokens(value: str) -> list[str]:
    """관심 후보로 사용할 한국어·영문 Token을 중복 없이 추출한다."""
    result: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN_PATTERN.findall(value):
        normalized = token.casefold()
        if normalized in _STOP_WORDS or normalized in seen:
            continue
        seen.add(normalized)
        result.append(token)
    return result


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def int_001(
    documents: Sequence[Mapping[str, object]], *, limit: int = 20
) -> list[InterestCandidate]:
    """[INT-001] 관심사 Topic 추출.

    현재 Wiki 문서 Metadata의 반복도와 중요도로 관심 키워드를 계산한다.

    Args:
        documents: 활성 Wiki Build의 문서 Row 목록
        limit: 반환할 최대 관심 후보 수 (1~100)

    Returns:
        점수 내림차순으로 정렬된 관심 후보 목록
    """
    if not 1 <= limit <= 100:
        raise ValueError("관심 후보 limit은 1에서 100 사이여야 합니다.")
    weights: defaultdict[str, float] = defaultdict(float)
    labels: dict[str, str] = {}
    categories: dict[str, str | None] = {}
    evidence_documents: defaultdict[str, set[str]] = defaultdict(set)
    evidence_reasons: defaultdict[str, set[str]] = defaultdict(set)

    def add(topic: str, weight: float, document_id: str, reason: str, category: str | None) -> None:
        """정규화된 관심 Topic에 점수와 근거를 누적한다."""
        value = topic.strip()
        key = value.casefold()
        if not value or key in _STOP_WORDS:
            return
        labels.setdefault(key, value)
        weights[key] += weight
        evidence_documents[key].add(document_id)
        evidence_reasons[key].add(reason)
        if category and category != "other":
            categories.setdefault(key, category)

    for document in documents:
        document_id = str(document.get("document_id") or "")
        if not document_id:
            continue
        title = str(document.get("title") or "").strip()
        summary = str(document.get("summary") or "")
        domain = str(document.get("domain") or "").strip() or None
        metadata_value = document.get("source_metadata")
        metadata = metadata_value if isinstance(metadata_value, Mapping) else {}
        if title:
            add(title, 5.0, document_id, "title", domain)
        if domain and domain != "other":
            add(domain, 2.0, document_id, "domain", domain)
        for field_name in ("aliases", "tags"):
            values = metadata.get(field_name, [])
            if isinstance(values, list):
                for value in values:
                    add(str(value), 3.0, document_id, field_name, domain)
        for token in _tokens(title):
            add(token, 2.0, document_id, "title_token", domain)
        for token in _tokens(summary):
            add(token, 1.0, document_id, "summary_token", domain)

    if not weights:
        return []
    max_weight = max(weights.values())
    ordered = sorted(
        weights,
        key=lambda key: (
            -weights[key],
            -len(evidence_documents[key]),
            labels[key].casefold(),
        ),
    )[:limit]
    return [
        InterestCandidate(
            topic=labels[key],
            category=categories.get(key),
            score=round(min(1.0, weights[key] / max_weight), 6),
            confidence=round(
                min(
                    0.99,
                    0.45
                    + len(evidence_documents[key]) * 0.1
                    + min(weights[key], 10.0) * 0.03,
                ),
                6,
            ),
            document_ids=tuple(sorted(evidence_documents[key])),
            evidence={
                "weight": weights[key],
                "reasons": sorted(evidence_reasons[key]),
            },
        )
        for key in ordered
    ]
