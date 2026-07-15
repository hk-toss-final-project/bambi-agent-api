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
    degree: int = Field(ge=0, description="현재 Graph에서 연결된 Edge 개수")


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
