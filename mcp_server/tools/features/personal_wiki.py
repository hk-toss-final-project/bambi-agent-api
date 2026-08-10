"""Personal Wiki MCP 검색·문서 조회·Source 추가·구조화 문서 저장 기능."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field

from shared.wiki_models import (
    ConceptClassification,
    EntityClassification,
    WikiClassification,
    WikiRelationClassification,
)


class PersonalWikiMcpReader(Protocol):
    """Personal Wiki MCP 도구가 사용하는 읽기 저장소 계약."""

    async def search_documents(
        self, user_id: str, *, query: str, limit: int
    ) -> Sequence[Mapping[str, object]]:
        """사용자 Namespace에서 질의와 일치하는 문서를 검색한다."""
        ...

    async def get_document(
        self, user_id: str, document_id: str
    ) -> Mapping[str, object] | None:
        """사용자 Namespace의 문서 상세를 조회한다."""
        ...


class PersonalWikiMcpWriter(Protocol):
    """Personal Wiki MCP 도구가 사용하는 쓰기 저장소 계약."""

    async def add_source(
        self,
        user_id: str,
        *,
        title: str,
        content: str,
        tags: Sequence[str],
        memo: str | None,
        occurred_at: datetime | None,
    ) -> Mapping[str, object]:
        """사용자 Namespace에 원본을 Build Job 없이 저장만 한다."""
        ...


class PersonalWikiMcpEntryWriter(Protocol):
    """Claude가 분류한 구조화 문서를 저장하는 쓰기 저장소 계약."""

    async def save_structured_entry(
        self,
        user_id: str,
        *,
        source_document_version_id: str,
        classification: WikiClassification,
        model: str,
    ) -> Mapping[str, object]:
        """분류 결과를 기존 Build 파이프라인으로 검증·저장한다."""
        ...


class PersonalWikiMcpRebuildTrigger(Protocol):
    """저장된 원본의 서버 LLM 재구성을 요청하는 저장소 계약."""

    async def trigger_rebuild(
        self, user_id: str, *, source_document_version_id: str, request_id: str | None
    ) -> Mapping[str, object]:
        """서버 LLM 파이프라인으로 원본을 재구성하도록 Job을 등록한다."""
        ...


class WikiSearchResult(BaseModel):
    """LLM이 후속 fetch 대상을 고를 수 있는 Wiki 검색 결과."""

    id: str
    title: str
    url: str
    text: str
    metadata: dict[str, object] = Field(default_factory=dict)


class WikiSearchOutput(BaseModel):
    """표준 search MCP Tool의 구조화된 결과."""

    results: list[WikiSearchResult] = Field(default_factory=list)


class WikiFetchOutput(BaseModel):
    """표준 fetch MCP Tool의 문서 본문과 출처 Metadata."""

    id: str
    title: str
    text: str
    url: str
    metadata: dict[str, object] = Field(default_factory=dict)


async def mcptool_001(
    reader: PersonalWikiMcpReader,
    *,
    user_id: str,
    query: str,
    limit: int,
) -> WikiSearchOutput:
    """[MCPTOOL-001] Personal Wiki 검색.

    승인된 사용자의 개인 Wiki만 검색하며 일치하지 않으면 빈 결과를 반환한다.
    """
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("검색어를 입력해야 합니다.")
    rows = await reader.search_documents(
        user_id,
        query=normalized_query,
        limit=min(20, max(1, limit)),
    )
    return WikiSearchOutput(
        results=[
            WikiSearchResult(
                id=str(row["document_id"]),
                title=str(row["title"]),
                url=f"bambi://wiki/documents/{row['document_id']}",
                text=str(row.get("summary") or ""),
                metadata={
                    "document_kind": str(row["document_kind"]),
                    "updated_at": _serialize_datetime(row.get("updated_at")),
                },
            )
            for row in rows
        ]
    )


async def mcptool_002(
    reader: PersonalWikiMcpReader, *, user_id: str, document_id: str
) -> WikiFetchOutput:
    """[MCPTOOL-002] Personal Wiki 문서 조회.

    개인 Wiki의 특정 문서를 조회한다.
    """
    row = await reader.get_document(user_id, document_id)
    if row is None:
        raise ValueError("Personal Wiki 문서를 찾을 수 없습니다.")
    sources = row.get("sources")
    source_items = list(sources) if isinstance(sources, list) else []
    source_urls = [
        str(source["canonical_url"])
        for source in source_items
        if isinstance(source, Mapping) and source.get("canonical_url")
    ]
    return WikiFetchOutput(
        id=str(row["document_id"]),
        title=str(row["title"]),
        text=str(row.get("markdown") or ""),
        url=f"bambi://wiki/documents/{row['document_id']}",
        metadata={
            "document_kind": str(row["document_kind"]),
            "summary": str(row.get("summary") or ""),
            "updated_at": _serialize_datetime(row.get("updated_at")),
            "source_urls": source_urls,
        },
    )


def _serialize_datetime(value: object) -> str | None:
    """MCP Metadata의 날짜 값을 ISO 8601 문자열로 정규화한다."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


_MAX_SOURCE_CONTENT_LENGTH = 200_000


class SourceAddOutput(BaseModel):
    """Personal Wiki Source 추가 결과로 반환하는 저장된 원본 식별자."""

    source_document_id: str
    source_document_version_id: str
    source_version: int


async def mcptool_003(
    writer: PersonalWikiMcpWriter,
    *,
    user_id: str,
    title: str,
    content: str,
    tags: Sequence[str] = (),
    memo: str | None = None,
    occurred_at: datetime | None = None,
) -> SourceAddOutput:
    """[MCPTOOL-003] Personal Wiki Source 추가.

    사용자 승인 하에 Wiki Source를 저장만 한다. Entity·Concept 반영은 하지
    않으므로, 반영하려면 구조화 문서 저장(MCPTOOL-013)이나 재빌드 요청을
    이어서 호출해야 한다. 같은 본문을 다시 보내면 새 Version을 만들지 않는다.
    """
    normalized_title = title.strip()
    if not normalized_title:
        raise ValueError("Source 제목을 입력해야 합니다.")
    normalized_content = content.strip()
    if not normalized_content:
        raise ValueError("Source 본문을 입력해야 합니다.")
    if len(normalized_content) > _MAX_SOURCE_CONTENT_LENGTH:
        raise ValueError(
            f"Source 본문은 {_MAX_SOURCE_CONTENT_LENGTH}자를 넘을 수 없습니다."
        )
    result = await writer.add_source(
        user_id,
        title=normalized_title,
        content=normalized_content,
        tags=list(tags),
        memo=memo,
        occurred_at=occurred_at,
    )
    return SourceAddOutput(
        source_document_id=str(result["source_document_id"]),
        source_document_version_id=str(result["source_document_version_id"]),
        source_version=int(result["source_version"]),
    )


_ENTITY_SUBTYPES = frozenset(
    {"person", "organization", "project", "product", "event", "place", "other"}
)
_CONCEPT_SUBTYPES = frozenset(
    {"theory", "method", "field", "phenomenon", "standard", "term", "other"}
)
_NODE_KINDS = frozenset({"entity", "concept"})


class ClaudeEntityInput(BaseModel):
    """Claude가 원문에서 판단한 entity 후보 하나."""

    name: str = Field(min_length=1, max_length=200)
    subtype: str = "other"
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    related_entity_names: list[str] = Field(default_factory=list)
    related_concepts: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)


class ClaudeConceptInput(BaseModel):
    """Claude가 원문에서 판단한 concept 후보 하나."""

    title: str = Field(min_length=1, max_length=200)
    subtype: str = "other"
    definition: str = ""
    key_characteristics: list[str] = Field(default_factory=list)
    applications: list[str] = Field(default_factory=list)
    related_entity_names: list[str] = Field(default_factory=list)
    related_concepts: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)


class ClaudeRelationInput(BaseModel):
    """Claude가 원문 근거와 함께 판단한 entity·concept 간 관계 후보 하나."""

    source_name: str = Field(min_length=1)
    source_kind: str
    target_name: str = Field(min_length=1)
    target_kind: str
    relation_type: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    confidence: float = 1.0


class StructuredEntrySaveOutput(BaseModel):
    """Personal Wiki 구조화 문서 저장 결과 요약."""

    wiki_version_id: str
    affected_document_count: int
    quality_passed: bool
    quality_warning_count: int


async def mcptool_013(
    writer: PersonalWikiMcpEntryWriter,
    *,
    user_id: str,
    source_document_version_id: str,
    entities: Sequence[ClaudeEntityInput] = (),
    concepts: Sequence[ClaudeConceptInput] = (),
    relations: Sequence[ClaudeRelationInput] = (),
    source_summary: str = "",
) -> StructuredEntrySaveOutput:
    """[MCPTOOL-013] Personal Wiki 구조화 문서 저장.

    Claude가 분류한 entity/concept 항목을 검증 후 개인 Wiki에 저장한다. 서버
    LLM 원문 분류 호출 없이 기존 Build 파이프라인(중복 판정·품질 게이트·
    재임베딩)을 그대로 재사용한다. 저장 전 add_source(MCPTOOL-003)로 원본을
    먼저 저장해 source_document_version_id를 확보해야 한다.
    """
    if not source_document_version_id:
        raise ValueError("source_document_version_id가 필요합니다.")
    if not entities and not concepts:
        raise ValueError("최소 1개의 entity 또는 concept이 필요합니다.")
    for entity in entities:
        if entity.subtype not in _ENTITY_SUBTYPES:
            raise ValueError(f"허용하지 않는 entity 서브타입입니다: {entity.subtype}")
    for concept in concepts:
        if concept.subtype not in _CONCEPT_SUBTYPES:
            raise ValueError(f"허용하지 않는 concept 서브타입입니다: {concept.subtype}")
    for relation in relations:
        if relation.source_kind not in _NODE_KINDS or relation.target_kind not in _NODE_KINDS:
            raise ValueError(
                "relation의 source_kind/target_kind는 entity 또는 concept이어야 합니다."
            )
        if not 0.0 <= relation.confidence <= 1.0:
            raise ValueError("relation의 confidence는 0과 1 사이여야 합니다.")

    classification = WikiClassification(
        source_summary=source_summary,
        entities=[
            EntityClassification(
                name=item.name,
                subtype=item.subtype,
                description=item.description,
                aliases=list(item.aliases),
                related_entity_names=list(item.related_entity_names),
                related_concepts=list(item.related_concepts),
                mentions=list(item.mentions),
            )
            for item in entities
        ],
        concepts=[
            ConceptClassification(
                title=item.title,
                subtype=item.subtype,
                definition=item.definition,
                key_characteristics=list(item.key_characteristics),
                applications=list(item.applications),
                related_entity_names=list(item.related_entity_names),
                related_concepts=list(item.related_concepts),
                aliases=list(item.aliases),
                mentions=list(item.mentions),
            )
            for item in concepts
        ],
        relations=[
            WikiRelationClassification(
                source_name=item.source_name,
                source_kind=item.source_kind,
                target_name=item.target_name,
                target_kind=item.target_kind,
                relation_type=item.relation_type,
                evidence=item.evidence,
                provenance_kind="source_explicit",
                confidence=item.confidence,
                review_status="accepted",
                model="claude-mcp-write",
            )
            for item in relations
        ],
    )
    result = await writer.save_structured_entry(
        user_id,
        source_document_version_id=source_document_version_id,
        classification=classification,
        model="claude-mcp-write",
    )
    return StructuredEntrySaveOutput(
        wiki_version_id=str(result["wiki_version_id"]),
        affected_document_count=int(result["affected_document_count"]),
        quality_passed=bool(result["quality_passed"]),
        quality_warning_count=int(result["quality_warning_count"]),
    )


class RebuildTriggerOutput(BaseModel):
    """Personal Wiki 재빌드 트리거 결과로 반환하는 Job 식별자."""

    job_id: str
    job_created: bool


async def mcptool_014(
    trigger: PersonalWikiMcpRebuildTrigger,
    *,
    user_id: str,
    source_document_version_id: str,
    request_id: str | None = None,
) -> RebuildTriggerOutput:
    """[MCPTOOL-014] Personal Wiki 재빌드 트리거.

    저장된 Source를 서버 LLM 파이프라인으로 재구성하도록 요청한다. Claude가
    구조화 문서 저장(MCPTOOL-013)을 직접 못 했을 때 쓰는 폴백 경로다. 같은
    원본·Version을 다시 요청해도 Job을 중복 생성하지 않는다.
    """
    result = await trigger.trigger_rebuild(
        user_id,
        source_document_version_id=source_document_version_id,
        request_id=request_id,
    )
    return RebuildTriggerOutput(
        job_id=str(result["job_id"]),
        job_created=bool(result["job_created"]),
    )
