"""개인 Wiki Graph API 요청·응답 스키마.

현재 사용자 Namespace의 Entity·Concept 문서와 관계를 시각화 페이지가
안전하게 소비할 수 있는 Node·Edge 구조로 정의한다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WikiGraphSchema(BaseModel):
    """Wiki Graph 응답 모델의 변경 불가능한 공통 기반."""

    model_config = ConfigDict(frozen=True)


class WikiGraphNode(WikiGraphSchema):
    """현재 Wiki 문서 Version을 나타내는 Graph Node."""

    id: str = Field(description="Wiki 문서 UUID")
    document_kind: Literal["entity", "concept"] = Field(
        description="Wiki 문서 종류"
    )
    document_key: str = Field(description="사용자 Namespace 안의 논리 문서 Key")
    title: str = Field(description="화면에 표시할 Wiki 문서 제목")
    subtype: str = Field(description="Entity 또는 Concept 세부 유형")
    summary: str | None = Field(default=None, description="Wiki 문서 요약")
    aliases: list[str] = Field(default_factory=list, description="문서 별칭 목록")
    file_path: str = Field(description="Obsidian Vault 호환 문서 경로")
    version: int = Field(ge=1, description="현재 Wiki 문서 Version")
    updated_at: datetime = Field(description="Wiki Head 마지막 갱신 시각")
    markdown: str = Field(description="현재 Version의 정규화된 Markdown 본문")
    degree: int = Field(
        ge=0,
        description="현재 Graph에서 중복 관계 유형을 제외한 인접 노드 수",
    )


class WikiGraphEdge(WikiGraphSchema):
    """두 Wiki 문서 사이의 방향성 관계 Edge."""

    id: str = Field(description="Graph 안에서 안정적인 Edge 식별자")
    source: str = Field(description="출발 Wiki 문서 UUID")
    target: str = Field(description="도착 Wiki 문서 UUID")
    relation_type: Literal[
        "entity_relation",
        "applies_concept",
        "related_concept",
        "alias_of",
        "instance_of",
        "subtopic_of",
        "part_of",
        "located_in",
        "occurs_in",
        "affects",
        "causes",
        "associated_with",
    ] = Field(description="Wiki 문서 관계 유형")
    metadata: dict[str, object] = Field(
        default_factory=dict, description="관계 생성 과정의 부가 Metadata"
    )


class WikiGraphStats(WikiGraphSchema):
    """현재 개인 Wiki Graph의 집계 수치."""

    node_count: int = Field(ge=0, description="전체 Node 개수")
    edge_count: int = Field(ge=0, description="전체 Edge 개수")
    entity_count: int = Field(ge=0, description="Entity Node 개수")
    concept_count: int = Field(ge=0, description="Concept Node 개수")
    orphan_count: int = Field(ge=0, description="연결이 없는 Node 개수")


class WikiGraphResponse(WikiGraphSchema):
    """PWIKI-003 개인 Wiki Graph 조회 결과."""

    feature_id: str = Field(default="PWIKI-003", description="명세 기능 ID")
    user_id: str = Field(description="조회 대상 사용자 ID")
    namespace_key: str = Field(description="조회한 사용자 Wiki Namespace")
    wiki_version: int | None = Field(
        default=None, ge=1, description="현재 활성 Wiki Build Version"
    )
    generated_at: datetime | None = Field(
        default=None, description="현재 Wiki Build 활성화 시각"
    )
    stats: WikiGraphStats = Field(description="Graph 집계 수치")
    nodes: list[WikiGraphNode] = Field(description="현재 Entity·Concept Node 목록")
    edges: list[WikiGraphEdge] = Field(description="현재 Wiki 문서 관계 목록")


class WikiTopNode(WikiGraphSchema):
    """고유 인접 Node 수 기준으로 정렬된 Wiki 문서 Node 요약."""

    rank: int = Field(
        ge=1,
        description="고유 인접 Node 수 기준 순위. 1이 가장 많이 연결된 Node",
    )
    document_id: str = Field(description="Wiki 문서 UUID")
    document_kind: Literal["entity", "concept"] = Field(description="Wiki 문서 종류")
    document_key: str = Field(description="사용자 Namespace 안의 논리 문서 Key")
    title: str = Field(description="Wiki 문서 제목")
    subtype: str = Field(description="Entity 또는 Concept 세부 유형")
    degree: int = Field(
        ge=0,
        description="현재 Graph에서 중복 관계 유형을 제외한 인접 노드 수",
    )
    summary: str | None = Field(default=None, description="Wiki 문서 요약")
    aliases: list[str] = Field(default_factory=list, description="문서 별칭 목록")
    file_path: str = Field(description="Obsidian Vault 호환 문서 경로")


class WikiTopNodesResponse(WikiGraphSchema):
    """연결이 많은 순서로 정렬한 개인 Wiki Node 목록."""

    feature_id: str = Field(default="PWIKI-003", description="명세 기능 ID")
    user_id: str = Field(description="조회 대상 사용자 ID")
    namespace_key: str = Field(description="조회한 사용자 Wiki Namespace")
    wiki_version: int | None = Field(
        default=None, ge=1, description="현재 활성 Wiki Build Version"
    )
    total_node_count: int = Field(ge=0, description="현재 Graph의 전체 Node 수")
    items: list[WikiTopNode] = Field(description="연결 수 내림차순 상위 Node 목록")


WikiDocumentKind = Literal["document", "entity", "concept", "schema"]


class WikiDocumentSummary(WikiGraphSchema):
    """개인 Wiki 목록에 표시할 현재 문서 Version 요약."""

    document_id: str = Field(description="Wiki 문서 Head UUID")
    document_version_id: str = Field(description="현재 Wiki 문서 Version UUID")
    document_kind: WikiDocumentKind = Field(description="Wiki 문서 종류")
    document_key: str = Field(description="Namespace 안의 논리 문서 Key")
    file_path: str = Field(description="Obsidian Vault 파일 경로")
    domain: str | None = Field(default=None, description="Entity·Concept 세부 영역")
    title: str = Field(description="현재 Version 제목")
    summary: str | None = Field(default=None, description="현재 Version 요약")
    version: int = Field(ge=1, description="현재 문서 Version 번호")
    source_count: int = Field(ge=0, description="현재 Version에 연결된 원본 수")
    updated_at: datetime = Field(description="문서 Head 마지막 갱신 시각")


class WikiDocumentListResponse(WikiGraphSchema):
    """사용자 Namespace의 현재 Wiki 문서 목록."""

    feature_id: str = Field(default="PWIKI-003", description="명세 기능 ID")
    user_id: str = Field(description="조회 대상 사용자 ID")
    namespace_key: str = Field(description="조회한 사용자 Namespace")
    total: int = Field(ge=0, description="필터 조건에 맞는 전체 문서 수")
    items: list[WikiDocumentSummary] = Field(description="현재 Wiki 문서 목록")


class WikiDocumentSource(WikiGraphSchema):
    """Wiki 문서 Version이 참고한 사용자 원본 Version."""

    source_document_id: str = Field(description="사용자 원본 Head UUID")
    source_document_version_id: str = Field(description="사용자 원본 Version UUID")
    source_type: str = Field(description="클리핑·URL 등 원본 유형")
    source_version: int = Field(ge=1, description="원본 Version 번호")
    title: str = Field(description="원본 제목")
    canonical_url: str | None = Field(default=None, description="원본 URL")
    relation_type: str = Field(description="Wiki 문서와 원본의 관계")


class WikiDocumentRelation(WikiGraphSchema):
    """상세 Wiki 문서와 다른 논리 문서의 관계."""

    direction: Literal["outgoing", "incoming"] = Field(description="관계 방향")
    related_document_id: str = Field(description="상대 Wiki 문서 UUID")
    related_document_kind: WikiDocumentKind = Field(description="상대 문서 종류")
    related_document_key: str = Field(description="상대 문서 논리 Key")
    related_title: str = Field(description="상대 문서 현재 제목")
    relation_type: str = Field(description="관계 유형")
    metadata: dict[str, object] = Field(default_factory=dict, description="관계 Metadata")


class WikiDocumentDetailResponse(WikiDocumentSummary):
    """Frontmatter 포함 Markdown과 출처·관계를 포함한 Wiki 문서 상세."""

    feature_id: str = Field(default="PWIKI-003", description="명세 기능 ID")
    user_id: str = Field(description="조회 대상 사용자 ID")
    namespace_key: str = Field(description="조회한 사용자 Namespace")
    markdown: str = Field(description="현재 Version의 완성 Markdown")
    source_metadata: dict[str, object] = Field(
        default_factory=dict, description="Wiki Builder Metadata"
    )
    sources: list[WikiDocumentSource] = Field(description="참고한 사용자 원본")
    relations: list[WikiDocumentRelation] = Field(description="다른 Wiki 문서와의 관계")


class WikiBuildDocument(WikiGraphSchema):
    """특정 Wiki Build에 고정된 문서 Version과 파일 경로."""

    document_id: str = Field(description="Wiki 문서 Head UUID")
    document_version_id: str = Field(description="고정된 Wiki Version UUID")
    document_kind: WikiDocumentKind = Field(description="Wiki 문서 종류")
    document_key: str = Field(description="논리 문서 Key")
    file_path: str = Field(description="Build 당시 파일 경로")
    version: int = Field(ge=1, description="Build에 포함된 문서 Version")
    title: str = Field(description="Build 당시 문서 제목")


class WikiBuildDetailResponse(WikiGraphSchema):
    """하나의 활성·과거 Wiki Build Snapshot 상세."""

    feature_id: str = Field(default="PWIKI-006", description="명세 기능 ID")
    wiki_version_id: str = Field(description="Wiki Build UUID")
    user_id: str = Field(description="Wiki 소유 사용자 ID")
    namespace_key: str = Field(description="사용자 Wiki Namespace")
    version: int = Field(ge=1, description="사용자별 Wiki Build Version")
    status: Literal["building", "active", "failed", "retired"] = Field(
        description="Wiki Build 상태"
    )
    document_count: int = Field(ge=0, description="Build 문서 수")
    chunk_count: int = Field(ge=0, description="Build 검색 Chunk 수")
    change_summary: dict[str, object] = Field(description="Build 변경 요약")
    created_at: datetime = Field(description="Build 생성 시각")
    activated_at: datetime | None = Field(default=None, description="Build 활성화 시각")
    documents: list[WikiBuildDocument] = Field(description="Build에 고정된 문서 목록")
