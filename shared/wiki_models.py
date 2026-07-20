"""개인 LLM Wiki 계층 경계에서 공유하는 순수 데이터 구조.

DB 스키마나 LLM 호출에 의존하지 않는 값 객체만 모아, agent(분류·계획)와
infrastructure(영속화)가 서로를 import하지 않고도 같은 타입을 공유하게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ExistingWikiEntry:
    """Namespace에 이미 존재하는 entity 또는 concept 문서 한 건."""

    document_kind: str
    document_key: str
    title: str
    domain: str | None
    summary: str | None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EntityClassification:
    """LLM이 판단한 사람·조직·제품 등의 entity 후보 한 건."""

    name: str
    subtype: str = "other"
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    related_entity_names: list[str] = field(default_factory=list)
    related_concepts: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    matched_existing_key: str | None = None
    is_alias: bool = False


@dataclass(frozen=True, slots=True)
class ConceptClassification:
    """LLM이 판단한 이론·방법·분야·용어 등의 concept 후보 한 건."""

    title: str
    subtype: str = "other"
    definition: str = ""
    key_characteristics: list[str] = field(default_factory=list)
    applications: list[str] = field(default_factory=list)
    related_entity_names: list[str] = field(default_factory=list)
    related_concepts: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    matched_existing_key: str | None = None
    overlaps_existing: bool = False


@dataclass(frozen=True, slots=True)
class WikiClassification:
    """LLM 분류 호출 한 번의 전체 결과."""

    source_summary: str = ""
    entities: list[EntityClassification] = field(default_factory=list)
    concepts: list[ConceptClassification] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WikiDocumentPlan:
    """wiki_documents Row 한 건으로 저장될 예정인 entity/concept/schema 문서."""

    document_kind: str
    document_key: str
    file_path: str
    domain: str | None
    title: str
    summary: str
    normalized_content: str
    action: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WikiRelationPlan:
    """wiki_document_relations Row 한 건으로 저장될 예정인 문서 간 관계."""

    source_document_key: str
    source_document_kind: str
    target_document_key: str
    target_document_kind: str
    relation_type: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GeneratedArtifact:
    """DB에 저장하지 않고 결과로만 반환하는 산출물(sources, index.md, log)."""

    file_path: str
    content: str


@dataclass(frozen=True, slots=True)
class WikiBuildPlan:
    """한 번의 Incremental Wiki Build가 만든 전체 산출물."""

    entities: list[WikiDocumentPlan]
    concepts: list[WikiDocumentPlan]
    schema: WikiDocumentPlan
    relations: list[WikiRelationPlan]
    index: GeneratedArtifact
    source_manifest: GeneratedArtifact
    log_entry: GeneratedArtifact


@dataclass(frozen=True, slots=True)
class InterestCandidate:
    """현재 Wiki에서 계산된 관심 Topic과 근거 문서 목록."""

    topic: str
    category: str | None
    score: float
    confidence: float
    document_ids: tuple[str, ...]
    evidence: dict[str, object]
