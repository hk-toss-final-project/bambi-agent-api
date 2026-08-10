"""LLM Wiki Navigator API 요청·응답 스키마.

Consumer가 후보 Page를 찾고 선택한 Page·관계·출처를 읽되 Navigator가
최종 답변을 만들지 않는 Read Interface 계약을 정의한다.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class WikiNavigationSchema(BaseModel):
    """Navigator API 모델의 변경 불가능한 공통 기반."""

    model_config = ConfigDict(frozen=True, from_attributes=True)


class WikiNavigateRequest(WikiNavigationSchema):
    """후보 Locate 또는 선택 Page Navigation 요청."""

    query: str = Field(min_length=1, max_length=1000, description="탐색할 질문")
    selected_document_version_ids: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="Consumer가 후보에서 선택한 Wiki Page Version UUID",
    )
    wiki_version_id: str | None = Field(
        default=None, description="읽기를 고정할 Wiki Build UUID"
    )
    candidate_limit: int = Field(
        default=30, ge=1, le=30, description="Locate 후보 상한"
    )
    max_depth: int = Field(default=1, ge=0, le=2, description="관계 탐색 깊이")
    max_pages: int = Field(default=6, ge=1, le=6, description="읽을 Page 상한")
    max_chunks: int = Field(default=12, ge=1, le=12, description="읽을 Chunk 상한")


class WikiNavigationCandidateResponse(WikiNavigationSchema):
    """Logical Index에서 찾은 Wiki Page 후보."""

    document_id: str
    document_version_id: str
    document_kind: str
    document_key: str
    file_path: str
    title: str
    aliases: list[str]
    summary: str
    updated_at: datetime
    exact_match: bool
    alias_match: bool
    keyword_rank: int | None
    vector_rank: int | None
    rrf_score: float


class WikiNavigationExcerptResponse(WikiNavigationSchema):
    """Wiki Page에서 선택한 Chunk 발췌."""

    chunk_id: str
    chunk_index: int
    content: str
    heading_path: list[str]


class WikiNavigationPageResponse(WikiNavigationSchema):
    """정확한 Version으로 읽은 Wiki Page."""

    document_id: str
    document_version_id: str
    document_kind: str
    document_key: str
    file_path: str
    title: str
    aliases: list[str]
    summary: str
    markdown: str
    version: int
    updated_at: datetime
    role: str
    excerpts: list[WikiNavigationExcerptResponse]


class WikiNavigationRelationSupportResponse(WikiNavigationSchema):
    """Wiki 관계를 지지하는 원본 Version 근거."""

    source_document_version_id: str
    provenance_kind: str
    confidence: float
    review_status: str
    evidence: str
    rationale: str


class WikiNavigationRelationResponse(WikiNavigationSchema):
    """Page 탐색 중 통과한 검증 관계."""

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
    supports: list[WikiNavigationRelationSupportResponse]


class WikiNavigationSourceResponse(WikiNavigationSchema):
    """Wiki Page가 참고한 사용자 원본과 저장 시각."""

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


class WikiNavigationTraceStepResponse(WikiNavigationSchema):
    """Locate·Read·Traverse 단계의 최소 실행 기록."""

    step: str
    document_ids: list[str]
    details: list[tuple[str, str]]


class WikiNavigateResponse(WikiNavigationSchema):
    """최종 답변 없이 Page·관계·Source를 반환하는 Context Packet."""

    feature_id: str = Field(default="WNAV-006", description="명세 기능 ID")
    query: str
    wiki_version_id: str | None
    candidates: list[WikiNavigationCandidateResponse]
    pages: list[WikiNavigationPageResponse]
    relations: list[WikiNavigationRelationResponse]
    sources: list[WikiNavigationSourceResponse]
    trace: list[WikiNavigationTraceStepResponse]
    truncated: bool
    fallback_reason: str | None
