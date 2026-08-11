"""LLM Wiki Navigator가 계층 사이에서 공유하는 순수 데이터 구조.

개인 Wiki Page 후보, 읽은 Version, 검증 관계와 원본 출처를 구조화해
Navigator가 최종 답변 대신 Context Packet을 반환할 수 있게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class WikiNavigationCandidate:
    """Logical Index에서 회수한 Wiki Page 후보 한 건."""

    document_id: str
    document_version_id: str
    document_kind: str
    document_key: str
    file_path: str
    title: str
    aliases: tuple[str, ...]
    summary: str
    updated_at: datetime
    exact_match: bool = False
    alias_match: bool = False
    keyword_rank: int | None = None
    vector_rank: int | None = None
    rrf_score: float = 0.0
    keyword_score: float | None = None
    vector_score: float | None = None


@dataclass(frozen=True, slots=True)
class WikiNavigationExcerpt:
    """Wiki Page Version에서 읽은 검색 가능 Chunk 발췌."""

    chunk_id: str
    chunk_index: int
    content: str
    heading_path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WikiNavigationPage:
    """Navigator가 정확한 Version으로 읽은 Wiki Page."""

    document_id: str
    document_version_id: str
    document_kind: str
    document_key: str
    file_path: str
    title: str
    aliases: tuple[str, ...]
    summary: str
    markdown: str
    version: int
    updated_at: datetime
    role: str
    excerpts: tuple[WikiNavigationExcerpt, ...] = ()


@dataclass(frozen=True, slots=True)
class WikiNavigationRelationSupport:
    """Wiki 관계를 지지하는 활성 원본 Version 근거."""

    source_document_version_id: str
    provenance_kind: str
    confidence: float
    review_status: str
    evidence: str
    rationale: str


@dataclass(frozen=True, slots=True)
class WikiNavigationRelation:
    """Page 탐색 중 통과한 방향성 Wiki 관계."""

    relation_id: str
    source_document_id: str
    target_document_id: str
    relation_type: str
    confidence: float
    provenance_kind: str
    review_status: str
    rationale: str
    traversal_direction: str
    hops: int
    supports: tuple[WikiNavigationRelationSupport, ...] = ()


@dataclass(frozen=True, slots=True)
class WikiNavigationSource:
    """Wiki Page Version이 참고한 사용자 원본과 관심 시각."""

    wiki_document_version_id: str
    source_document_id: str
    source_document_version_id: str
    source_type: str
    title: str
    url: str | None
    relation_type: str
    saved_at: datetime
    saved_at_source: str
    stored_at: datetime
    published_at: datetime | None
    clipped_on: date | None
    image_url: str | None = None


@dataclass(frozen=True, slots=True)
class WikiNavigationTraceStep:
    """Navigator가 수행한 Locate·Read·Traverse 단계 기록."""

    step: str
    document_ids: tuple[str, ...] = ()
    details: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class WikiNavigationTraversal:
    """선택 Seed에서 제한적으로 순회한 Page와 관계 결과."""

    document_ids: tuple[str, ...]
    relations: tuple[WikiNavigationRelation, ...]
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class WikiNavigationPacket:
    """Consumer가 최종 추론에 사용할 구조화된 Wiki 읽기 결과."""

    query: str
    wiki_version_id: str | None
    candidates: tuple[WikiNavigationCandidate, ...]
    pages: tuple[WikiNavigationPage, ...]
    relations: tuple[WikiNavigationRelation, ...]
    sources: tuple[WikiNavigationSource, ...]
    trace: tuple[WikiNavigationTraceStep, ...]
    truncated: bool = False
    fallback_reason: str | None = None
