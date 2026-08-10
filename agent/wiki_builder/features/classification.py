"""개인 지식 Wiki를 위한 LLM 분류 기능 구현.

클리핑 원문을 손실 없이 청크로 나누고, 사람·조직·제품·장소 등의
entity와 이론·방법·분야·용어 등의 concept을 추출한다. 여러 청크의
결과는 안정적인 키로 병합하며, 원문에 실제로 있는 인용문과 관계만 보존한다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from agent.llm.api import complete, strip_json_fence
from agent.wiki_builder.features.relations import parse_relation_candidates
from agent.wiki_builder.models import (
    ConceptClassification,
    EntityClassification,
    ExistingWikiEntry,
    WikiClassification,
    WikiRelationClassification,
)
from shared.onboarding_context_models import OnboardingTopicContext

_MAX_SOURCE_CHARS = 8000
_ENTITY_SUBTYPES = {
    "person",
    "organization",
    "project",
    "product",
    "event",
    "place",
    "other",
}
_CONCEPT_SUBTYPES = {
    "theory",
    "method",
    "field",
    "phenomenon",
    "standard",
    "term",
    "other",
}
ONBOARDING_CLASSIFIER_MODEL = "deterministic:onboarding-seed-v1"

type WikiClassifier = Callable[..., WikiClassification]

_PROMPT_PATH = Path(__file__).parents[2] / "prompts" / "templates" / "personal_wiki_classifier.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()


def _unique(items: Iterable[str]) -> list[str]:
    """문자열 목록의 순서를 유지하며 빈 값과 중복을 제거한다."""
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = item.strip()
        marker = normalized.casefold()
        if normalized and marker not in seen:
            seen.add(marker)
            result.append(normalized)
    return result


def classify_onboarding_seed_for_wiki(
    source_metadata: Mapping[str, object],
    *,
    resolved_contexts: Sequence[OnboardingTopicContext] = (),
) -> WikiClassification:
    """해석된 온보딩 컨텍스트를 Entity·Concept 후보로 결정론 변환한다."""
    if resolved_contexts:
        names_by_topic_id = {
            context.topic_id: context.canonical_name
            for context in resolved_contexts
            if context.topic_id
        }
        entities: list[EntityClassification] = []
        concepts: list[ConceptClassification] = []
        for context in resolved_contexts:
            provenance: dict[str, object] = {
                "onboarding_context": {
                    "taxonomy_version": context.taxonomy_version,
                    "topic_id": context.topic_id,
                    "content_version": context.content_version,
                    "resolution_kind": context.resolution_kind,
                    "confidence": context.confidence,
                    "original_keyword": context.original_keyword,
                    "locale": context.locale,
                    "context_signature": context.context_signature,
                    "model_name": context.model_name,
                    "prompt_version": context.prompt_version,
                    **context.metadata,
                }
            }
            related_concepts = _unique(
                names_by_topic_id[topic_id]
                for topic_id in context.related_topic_ids
                if topic_id in names_by_topic_id
            )
            if context.node_kind == "entity":
                entities.append(
                    EntityClassification(
                        name=context.canonical_name,
                        subtype=context.subtype,
                        description=context.definition,
                        aliases=list(context.aliases),
                        related_concepts=related_concepts,
                        matched_existing_key=context.matched_existing_key,
                        context_metadata=provenance,
                    )
                )
            else:
                concepts.append(
                    ConceptClassification(
                        title=context.canonical_name,
                        subtype=context.subtype,
                        definition=context.definition,
                        key_characteristics=list(context.key_characteristics),
                        applications=list(context.applications),
                        aliases=list(context.aliases),
                        related_concepts=related_concepts,
                        matched_existing_key=context.matched_existing_key,
                        context_metadata=provenance,
                    )
                )
        return WikiClassification(
            source_summary=(
                "사용자가 온보딩에서 직접 선택하거나 입력한 관심 주제: "
                + ", ".join(context.original_keyword for context in resolved_contexts)
            ),
            entities=entities,
            concepts=concepts,
        )

    # 이전 Version의 시드도 재구성할 수 있게 label 전체를 하나의 Topic으로
    # 취급한다. `AI·머신러닝`처럼 가운데점이 있는 정식 명칭을 쪼개지 않는다.
    raw_labels = source_metadata.get("labels")
    if not isinstance(raw_labels, list):
        raise ValueError("온보딩 시드 metadata.labels가 문자열 목록이어야 합니다.")
    source_labels = _unique(item for item in raw_labels if isinstance(item, str))
    if not source_labels:
        raise ValueError("온보딩 시드에 유효한 관심 주제 label이 없습니다.")
    return WikiClassification(
        source_summary=(
            "사용자가 온보딩에서 직접 선택한 관심 주제: "
            + ", ".join(source_labels)
        ),
        concepts=[
            ConceptClassification(
                title=label,
                subtype="term",
                definition=f"사용자가 온보딩에서 직접 선택한 관심 주제: {label}",
            )
            for label in source_labels
        ],
    )


def _as_string_list(value: object) -> list[str]:
    """LLM JSON 값을 정제된 문자열 목록으로 변환한다."""
    if not isinstance(value, list):
        return []
    return _unique(str(item) for item in value)


def _format_existing_entries(entries: Sequence[ExistingWikiEntry]) -> str:
    """기존 entity·concept 목록을 중복 판단용 프롬프트로 정리한다."""
    if not entries:
        return "(없음)"
    lines: list[str] = []
    for entry in entries:
        summary = f" — {entry.summary}" if entry.summary else ""
        subtype = f" [subtype={entry.domain}]" if entry.domain else ""
        aliases = entry.metadata.get("aliases", [])
        alias_text = f" [aliases={', '.join(str(item) for item in aliases)}]" if aliases else ""
        lines.append(f"- key={entry.document_key}: {entry.title}{subtype}{alias_text}{summary}")
    return "\n".join(lines)


# 원문에서 노드가 맡은 역할. 관심사 후보를 고를 때 subject만 남긴다.
#
# 2026-08-07 실측: 관심사 상위권에 DBeaver Community·pgAdmin 4·OpenWiki(도구),
# "기술노트with 알렉"·"AI 시대 개발을 위한 필수 IT 지식"(출처), "API 키 발급"(절차),
# Cauchy·Kepler(글에 언급된 인물)이 올라와 있었다. 전부 글에서 스쳐 간 것이지
# 사용자가 뉴스로 받아보고 싶은 대상이 아니다. subtype으로는 못 가른다 —
# DBeaver Community와 리튬황 배터리가 둘 다 product였다.
_NODE_ROLES = {"subject", "tool", "source", "mention"}


def _validated_role(value: object) -> str:
    """LLM이 반환한 역할을 허용 목록으로 제한한다.

    값이 없거나 모르는 값이면 subject로 둔다. 판정에 실패했다고 관심사를
    통째로 잃는 것보다, 걸러내지 못하는 쪽이 덜 나쁘기 때문이다.
    """
    role = str(value or "subject").strip().lower()
    return role if role in _NODE_ROLES else "subject"


def _validated_subtype(value: object, allowed: set[str]) -> str:
    """LLM이 반환한 subtype을 허용 목록으로 제한한다."""
    subtype = str(value or "other").strip().lower()
    return subtype if subtype in allowed else "other"


def _validated_mentions(value: object, source_content: str | None) -> list[str]:
    """원문에 실제로 존재하는 verbatim 인용문만 반환한다."""
    mentions = _as_string_list(value)
    if source_content is None:
        return mentions
    return [mention for mention in mentions if mention in source_content]


def _parse_entity(
    raw: dict[str, object], source_content: str | None
) -> EntityClassification:
    """LLM JSON의 entity 항목을 검증된 데이터 객체로 변환한다."""
    return EntityClassification(
        name=str(raw.get("name") or "").strip(),
        subtype=_validated_subtype(raw.get("subtype"), _ENTITY_SUBTYPES),
        description=str(raw.get("description") or "").strip(),
        aliases=_as_string_list(raw.get("aliases")),
        related_entity_names=_as_string_list(raw.get("related_entity_names")),
        related_concepts=_as_string_list(raw.get("related_concepts")),
        mentions=_validated_mentions(raw.get("mentions"), source_content),
        matched_existing_key=(
            str(raw["matched_existing_key"]).strip()
            if raw.get("matched_existing_key")
            else None
        ),
        is_alias=bool(raw.get("is_alias", False)),
        role=_validated_role(raw.get("role")),
    )


def _parse_concept(
    raw: dict[str, object], source_content: str | None
) -> ConceptClassification:
    """LLM JSON의 concept 항목을 검증된 데이터 객체로 변환한다."""
    return ConceptClassification(
        title=str(raw.get("title") or "").strip(),
        subtype=_validated_subtype(raw.get("subtype"), _CONCEPT_SUBTYPES),
        definition=str(raw.get("definition") or "").strip(),
        key_characteristics=_as_string_list(raw.get("key_characteristics")),
        applications=_as_string_list(raw.get("applications")),
        related_entity_names=_as_string_list(raw.get("related_entity_names")),
        related_concepts=_as_string_list(raw.get("related_concepts")),
        aliases=_as_string_list(raw.get("aliases")),
        mentions=_validated_mentions(raw.get("mentions"), source_content),
        matched_existing_key=(
            str(raw["matched_existing_key"]).strip()
            if raw.get("matched_existing_key")
            else None
        ),
        overlaps_existing=bool(raw.get("overlaps_existing", False)),
        role=_validated_role(raw.get("role")),
    )


def _apply_relations_to_nodes(
    *,
    entities: Sequence[EntityClassification],
    concepts: Sequence[ConceptClassification],
    relations: Sequence[WikiRelationClassification],
) -> tuple[list[EntityClassification], list[ConceptClassification]]:
    """검증된 관계를 entity·concept Markdown용 관련 노드 목록에 반영한다."""
    entity_indexes: dict[str, int] = {}
    for index, entity in enumerate(entities):
        if entity.name.strip():
            entity_indexes[entity.name.strip().casefold()] = index
        if entity.matched_existing_key:
            entity_indexes[entity.matched_existing_key.casefold()] = index
    concept_indexes: dict[str, int] = {}
    for index, concept in enumerate(concepts):
        if concept.title.strip():
            concept_indexes[concept.title.strip().casefold()] = index
        if concept.matched_existing_key:
            concept_indexes[concept.matched_existing_key.casefold()] = index
    merged_entities = [
        replace(entity, related_entity_names=[], related_concepts=[])
        for entity in entities
    ]
    merged_concepts = [
        replace(concept, related_entity_names=[], related_concepts=[])
        for concept in concepts
    ]
    for relation in relations:
        source_marker = (
            relation.source_matched_key or relation.source_name
        ).casefold()
        target_marker = (
            relation.target_matched_key or relation.target_name
        ).casefold()
        if relation.source_kind == "entity" and relation.target_kind == "entity":
            source_index = entity_indexes.get(source_marker)
            target_index = entity_indexes.get(target_marker)
            if source_index is not None and target_index is not None:
                source = merged_entities[source_index]
                target_name = merged_entities[target_index].name
                merged_entities[source_index] = replace(
                    source,
                    related_entity_names=_unique(
                        [*source.related_entity_names, target_name]
                    ),
                )
        elif relation.source_kind == "entity" and relation.target_kind == "concept":
            source_index = entity_indexes.get(source_marker)
            target_index = concept_indexes.get(target_marker)
            if source_index is not None and target_index is not None:
                source = merged_entities[source_index]
                target_name = merged_concepts[target_index].title
                merged_entities[source_index] = replace(
                    source,
                    related_concepts=_unique(
                        [*source.related_concepts, target_name]
                    ),
                )
                target = merged_concepts[target_index]
                source_name = merged_entities[source_index].name
                merged_concepts[target_index] = replace(
                    target,
                    related_entity_names=_unique(
                        [*target.related_entity_names, source_name]
                    ),
                )
        elif relation.source_kind == "concept" and relation.target_kind == "concept":
            source_index = concept_indexes.get(source_marker)
            target_index = concept_indexes.get(target_marker)
            if source_index is not None and target_index is not None:
                source = merged_concepts[source_index]
                target_name = merged_concepts[target_index].title
                merged_concepts[source_index] = replace(
                    source,
                    related_concepts=_unique(
                        [*source.related_concepts, target_name]
                    ),
                )
    return merged_entities, merged_concepts


def parse_wiki_classification(
    raw_response: str, *, source_content: str | None = None
) -> WikiClassification:
    """LLM의 JSON 응답을 개인 지식 Wiki 분류 결과로 파싱한다."""
    text = strip_json_fence(raw_response)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"LLM Wiki 분류 응답이 JSON 형식이 아닙니다: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("LLM Wiki 분류 응답이 JSON 객체가 아닙니다.")

    entities: list[EntityClassification] = []
    concepts: list[ConceptClassification] = []
    node_refs: dict[str, tuple[str, str, str | None]] = {}
    reference_warnings: list[str] = []

    raw_entities = payload.get("entities") or []
    if isinstance(raw_entities, list):
        for item in raw_entities:
            if not isinstance(item, dict):
                continue
            entity = _parse_entity(item, source_content)
            if not entity.name:
                continue
            entities.append(entity)
            reference = str(item.get("ref") or "").strip()
            if reference and entity.name:
                marker = reference.casefold()
                if any(key.casefold() == marker for key in node_refs):
                    reference_warnings.append(f"중복 노드 참조를 제외했습니다: {reference}")
                else:
                    node_refs[reference] = (
                        "entity",
                        entity.name,
                        entity.matched_existing_key,
                    )

    raw_concepts = payload.get("concepts") or []
    if isinstance(raw_concepts, list):
        for item in raw_concepts:
            if not isinstance(item, dict):
                continue
            concept = _parse_concept(item, source_content)
            if not concept.title:
                continue
            concepts.append(concept)
            reference = str(item.get("ref") or "").strip()
            if reference and concept.title:
                marker = reference.casefold()
                if any(key.casefold() == marker for key in node_refs):
                    reference_warnings.append(f"중복 노드 참조를 제외했습니다: {reference}")
                else:
                    node_refs[reference] = (
                        "concept",
                        concept.title,
                        concept.matched_existing_key,
                    )

    relation_result = parse_relation_candidates(
        payload.get("relations"),
        node_refs=node_refs,
        source_content=source_content,
    )
    entities, concepts = _apply_relations_to_nodes(
        entities=entities,
        concepts=concepts,
        relations=relation_result.relations,
    )
    return WikiClassification(
        source_summary=str(payload.get("source_summary") or "").strip(),
        entities=entities,
        concepts=concepts,
        relations=relation_result.relations,
        relation_warnings=_unique(
            [*reference_warnings, *relation_result.warnings]
        ),
    )


def split_source_content(
    source_content: str, *, max_chars: int = _MAX_SOURCE_CHARS
) -> list[str]:
    """원문을 손실 없이 문단 경계 중심의 LLM 입력 청크로 나눈다."""
    text = source_content.strip()
    if not text:
        return []
    paragraphs = text.splitlines(keepends=True)
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        remaining = paragraph
        while remaining:
            available = max_chars - len(current)
            if available <= 0:
                chunks.append(current)
                current = ""
                available = max_chars
            current += remaining[:available]
            remaining = remaining[available:]
            if len(current) >= max_chars:
                chunks.append(current)
                current = ""
    if current:
        chunks.append(current)
    return chunks


def _merge_text(first: str, second: str) -> str:
    """서로 다른 두 설명을 중복 없이 하나의 문단으로 합친다."""
    if not first:
        return second
    if not second or second in first:
        return first
    if first in second:
        return second
    return f"{first}\n\n{second}"


def _merge_entity(
    current: EntityClassification, incoming: EntityClassification
) -> EntityClassification:
    """여러 원문 청크에서 추출된 같은 entity 정보를 병합한다."""
    return replace(
        current,
        description=_merge_text(current.description, incoming.description),
        aliases=_unique([*current.aliases, *incoming.aliases]),
        related_entity_names=_unique(
            [*current.related_entity_names, *incoming.related_entity_names]
        ),
        related_concepts=_unique(
            [*current.related_concepts, *incoming.related_concepts]
        ),
        mentions=_unique([*current.mentions, *incoming.mentions]),
        matched_existing_key=(
            current.matched_existing_key or incoming.matched_existing_key
        ),
        is_alias=current.is_alias or incoming.is_alias,
        context_metadata={
            **current.context_metadata,
            **incoming.context_metadata,
        },
    )


def _merge_concept(
    current: ConceptClassification, incoming: ConceptClassification
) -> ConceptClassification:
    """여러 원문 청크에서 추출된 같은 concept 정보를 병합한다."""
    return replace(
        current,
        definition=_merge_text(current.definition, incoming.definition),
        key_characteristics=_unique(
            [*current.key_characteristics, *incoming.key_characteristics]
        ),
        applications=_unique([*current.applications, *incoming.applications]),
        related_entity_names=_unique(
            [*current.related_entity_names, *incoming.related_entity_names]
        ),
        related_concepts=_unique(
            [*current.related_concepts, *incoming.related_concepts]
        ),
        aliases=_unique([*current.aliases, *incoming.aliases]),
        mentions=_unique([*current.mentions, *incoming.mentions]),
        matched_existing_key=(
            current.matched_existing_key or incoming.matched_existing_key
        ),
        overlaps_existing=current.overlaps_existing or incoming.overlaps_existing,
        context_metadata={
            **current.context_metadata,
            **incoming.context_metadata,
        },
    )


def merge_wiki_classifications(
    classifications: Sequence[WikiClassification],
) -> WikiClassification:
    """여러 원문 청크의 분류 결과를 하나의 Wiki 분류 결과로 합친다."""
    entities: dict[str, EntityClassification] = {}
    concepts: dict[str, ConceptClassification] = {}
    relations: dict[tuple[str, str, str, str, str], WikiRelationClassification] = {}
    summaries: list[str] = []
    relation_warnings: list[str] = []
    for classification in classifications:
        if classification.source_summary:
            summaries.append(classification.source_summary)
        for entity in classification.entities:
            key = (entity.matched_existing_key or entity.name).strip().casefold()
            if not key:
                continue
            entities[key] = (
                _merge_entity(entities[key], entity) if key in entities else entity
            )
        for concept in classification.concepts:
            key = (concept.matched_existing_key or concept.title).strip().casefold()
            if not key:
                continue
            concepts[key] = (
                _merge_concept(concepts[key], concept)
                if key in concepts
                else concept
            )
        for relation in classification.relations:
            signature = (
                relation.source_kind,
                (relation.source_matched_key or relation.source_name).casefold(),
                relation.target_kind,
                (relation.target_matched_key or relation.target_name).casefold(),
                relation.relation_type,
            )
            relations.setdefault(signature, relation)
        relation_warnings.extend(classification.relation_warnings)
    merged_entities, merged_concepts = _apply_relations_to_nodes(
        entities=list(entities.values()),
        concepts=list(concepts.values()),
        relations=list(relations.values()),
    )
    return WikiClassification(
        source_summary="\n\n".join(_unique(summaries)),
        entities=merged_entities,
        concepts=merged_concepts,
        relations=list(relations.values()),
        relation_warnings=_unique(relation_warnings),
    )


def classify_source_for_wiki(
    *,
    source_title: str,
    source_content: str,
    existing_entities: Sequence[ExistingWikiEntry],
    existing_concepts: Sequence[ExistingWikiEntry],
    source_description: str | None = None,
    source_tags: Sequence[str] = (),
    model: str = "gpt-4.1-mini",
) -> WikiClassification:
    """클리핑 원문 한 건을 개인 지식 entity·concept 후보로 분류한다.

    긴 원문은 여러 LLM 호출로 나누어 전체 내용을 보존하고, 각 호출의
    결과를 이름과 기존 document_key 기준으로 합친다. 관계는 이 단계에서
    확정하지 않고 identity 판정 후 Relation Linker가 전체 후보를 다시 검토한다.
    """
    chunks = split_source_content(source_content)
    if not chunks:
        return WikiClassification()
    classifications: list[WikiClassification] = []
    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        user_prompt = (
            f"[원본 제목]\n{source_title}\n\n"
            f"[원본 설명]\n{source_description or '(없음)'}\n\n"
            f"[원본 태그]\n{', '.join(source_tags) or '(없음)'}\n\n"
            f"[원본 본문 {index}/{total}]\n{chunk}\n\n"
            f"[기존 entity 목록]\n{_format_existing_entries(existing_entities)}\n\n"
            f"[기존 concept 목록]\n{_format_existing_entries(existing_concepts)}"
        )
        raw_response = complete(_SYSTEM_PROMPT, user_prompt, model=model)
        classification = parse_wiki_classification(
            raw_response, source_content=chunk
        )
        # 구버전 프롬프트·캐시가 relations을 반환해도 추출 단계에서는
        # Edge를 확정하지 않는다. 부분 Edge가 있으면 재검토를 건너뛰던
        # 기존 조건을 제거하고, Relation Linker가 항상 완전성을 판정한다.
        classification = replace(
            classification,
            entities=[
                replace(
                    entity,
                    related_entity_names=[],
                    related_concepts=[],
                )
                for entity in classification.entities
            ],
            concepts=[
                replace(
                    concept,
                    related_entity_names=[],
                    related_concepts=[],
                )
                for concept in classification.concepts
            ],
            relations=[],
            node_dispositions=[],
        )
        classifications.append(classification)
    return merge_wiki_classifications(classifications)


def classify_wiki_source(
    *,
    source_type: str,
    source_metadata: Mapping[str, object],
    source_title: str,
    source_content: str,
    existing_entities: Sequence[ExistingWikiEntry],
    existing_concepts: Sequence[ExistingWikiEntry],
    source_description: str | None = None,
    source_tags: Sequence[str] = (),
    model: str = "gpt-4.1-mini",
    classifier: WikiClassifier = classify_source_for_wiki,
    onboarding_contexts: Sequence[OnboardingTopicContext] = (),
) -> tuple[WikiClassification, str]:
    """원본 유형에 맞는 분류 결과와 Build 기록용 모델 표식을 반환한다."""
    if source_type == "onboarding_seed":
        return (
            classify_onboarding_seed_for_wiki(
                source_metadata,
                resolved_contexts=onboarding_contexts,
            ),
            ONBOARDING_CLASSIFIER_MODEL,
        )
    return (
        classifier(
            source_title=source_title,
            source_content=source_content,
            source_description=source_description,
            source_tags=source_tags,
            existing_entities=existing_entities,
            existing_concepts=existing_concepts,
            model=model,
        ),
        model,
    )
