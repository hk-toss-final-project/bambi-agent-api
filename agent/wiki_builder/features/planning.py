"""LLM 개인 지식 분류 결과를 Wiki Build 계획으로 변환하는 기능 구현.

기존 Namespace의 entity·concept Metadata를 보존하며 별칭·출처·관계·인용을
append-only 원칙으로 합친다. LLM이 만든 값을 DB에 바로 쓰지 않고,
시스템 날짜와 안정적인 문서 키를 주입한 뒤 Markdown을 렌더링한다.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from agent.wiki_builder.models import (
    ExistingWikiEntry,
    GeneratedArtifact,
    WikiBuildPlan,
    WikiClassification,
    WikiDocumentPlan,
    WikiRelationPlan,
)
from agent.wiki_builder.vault import (
    SCHEMA_DOCUMENT_KEY,
    SCHEMA_FILE_PATH,
    concept_file_path,
    entity_file_path,
    render_concept_markdown,
    render_entity_markdown,
    render_index_markdown,
    render_log_entry,
    render_schema_markdown,
    render_source_manifest_markdown,
    slugify,
    source_file_path,
)

_SUMMARY_PREVIEW_CHARS = 280


def _unique(items: Iterable[str]) -> list[str]:
    """순서를 유지하며 빈 문자열과 중복을 제거한다."""
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = item.strip()
        marker = value.casefold()
        if value and marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def _metadata_strings(metadata: dict[str, object], key: str) -> list[str]:
    """Metadata의 목록 값을 안전한 문자열 목록으로 변환한다."""
    value = metadata.get(key, [])
    if not isinstance(value, list):
        return []
    return _unique(str(item) for item in value)


def _metadata_mentions(metadata: dict[str, object]) -> list[tuple[str, str]]:
    """Metadata에 저장된 인용문과 출처 Link 쌍을 복원한다."""
    value = metadata.get("mention_entries", [])
    if not isinstance(value, list):
        return []
    entries: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote") or "").strip()
        source = str(item.get("source") or "").strip()
        if quote and source and (quote, source) not in entries:
            entries.append((quote, source))
    return entries


def _merge_text(existing: str, incoming: str) -> str:
    """기존 설명을 보존하며 실제로 새로운 설명만 덧붙인다."""
    if not existing:
        return incoming
    if not incoming or incoming in existing:
        return existing
    if existing in incoming:
        return incoming
    return f"{existing}\n\n{incoming}"


def _source_link(source_path: str, source_title: str) -> str:
    """source 파일 경로와 표시 제목을 포함한 Wiki Link를 만든다."""
    return f"[[{source_path.removesuffix('.md')}|{source_title}]]"


def _merge_entries(
    document_kind: str,
    existing: Sequence[ExistingWikiEntry],
    plans: Sequence[WikiDocumentPlan],
) -> list[ExistingWikiEntry]:
    """기존 목록에 이번 Build의 생성·갱신 문서를 반영한다."""
    merged = {entry.document_key: entry for entry in existing}
    for plan in plans:
        merged[plan.document_key] = ExistingWikiEntry(
            document_kind=document_kind,
            document_key=plan.document_key,
            title=plan.title,
            domain=plan.domain,
            summary=plan.summary,
            metadata=plan.metadata,
        )
    return list(merged.values())


def _plan_entities(
    *,
    classification: WikiClassification,
    existing_entities: Sequence[ExistingWikiEntry],
    source_title: str,
    source_link: str,
    generated_date: str,
) -> tuple[list[WikiDocumentPlan], dict[str, str]]:
    """entity 후보를 기존 Metadata와 합쳐 문서 저장 계획으로 변환한다."""
    existing_by_key = {entry.document_key: entry for entry in existing_entities}
    plans: list[WikiDocumentPlan] = []
    key_by_name = {
        entry.title.strip().casefold(): entry.document_key for entry in existing_entities
    }
    for candidate in classification.entities:
        name = candidate.name.strip()
        if not name:
            continue
        resolved_key = (
            candidate.matched_existing_key
            if candidate.matched_existing_key in existing_by_key
            else slugify(name)
        )
        existing = existing_by_key.get(resolved_key)
        old_metadata = existing.metadata if existing else {}
        title = existing.title if existing else name
        subtype = (
            existing.domain
            if existing and candidate.subtype == "other" and existing.domain
            else candidate.subtype
        )
        aliases = _unique(
            [
                *_metadata_strings(old_metadata, "aliases"),
                *candidate.aliases,
                *([name] if candidate.is_alias and name != title else []),
            ]
        )
        related_entities = _unique(
            [
                *_metadata_strings(old_metadata, "related_entities"),
                *candidate.related_entity_names,
            ]
        )
        related_concepts = _unique(
            [
                *_metadata_strings(old_metadata, "related_concepts"),
                *candidate.related_concepts,
            ]
        )
        mention_entries = [
            *_metadata_mentions(old_metadata),
            *((mention, source_link) for mention in candidate.mentions),
        ]
        mention_entries = list(dict.fromkeys(mention_entries))
        mentions = _unique(quote for quote, _mention_source in mention_entries)
        sources = _unique(
            [*_metadata_strings(old_metadata, "sources"), source_link]
        )
        old_description = str(
            old_metadata.get("description") or (existing.summary if existing else "") or ""
        )
        description = _merge_text(old_description, candidate.description)
        created = str(old_metadata.get("created") or generated_date)
        metadata: dict[str, object] = {
            "subtype": subtype,
            "aliases": aliases,
            "description": description,
            "related_entities": related_entities,
            "related_concepts": related_concepts,
            "mentions": mentions,
            "mention_entries": [
                {"quote": quote, "source": mention_source}
                for quote, mention_source in mention_entries
            ],
            "sources": sources,
            "created": created,
            "updated": generated_date,
        }
        content = render_entity_markdown(
            name=title,
            subtype=subtype,
            description=description,
            aliases=aliases,
            related_entities=related_entities,
            related_concepts=related_concepts,
            mention_entries=mention_entries,
            source_links=_metadata_strings(old_metadata, "sources"),
            source_title=source_title,
            source_link=source_link,
            created=created,
            updated=generated_date,
        )
        plans.append(
            WikiDocumentPlan(
                document_kind="entity",
                document_key=resolved_key,
                file_path=entity_file_path(resolved_key),
                domain=subtype,
                title=title,
                summary=description[:_SUMMARY_PREVIEW_CHARS],
                normalized_content=content,
                action="update" if existing else "create",
                metadata=metadata,
            )
        )
        key_by_name[name.casefold()] = resolved_key
        key_by_name[title.casefold()] = resolved_key
    return plans, key_by_name


def _plan_concepts(
    *,
    classification: WikiClassification,
    existing_concepts: Sequence[ExistingWikiEntry],
    source_link: str,
    generated_date: str,
) -> tuple[list[WikiDocumentPlan], dict[str, str]]:
    """concept 후보를 기존 Metadata와 합쳐 문서 저장 계획으로 변환한다."""
    existing_by_key = {entry.document_key: entry for entry in existing_concepts}
    plans: list[WikiDocumentPlan] = []
    key_by_title = {
        entry.title.strip().casefold(): entry.document_key for entry in existing_concepts
    }
    for candidate in classification.concepts:
        title = candidate.title.strip()
        if not title:
            continue
        resolved_key = (
            candidate.matched_existing_key
            if candidate.matched_existing_key in existing_by_key
            else slugify(title)
        )
        existing = existing_by_key.get(resolved_key)
        old_metadata = existing.metadata if existing else {}
        resolved_title = existing.title if existing else title
        subtype = (
            existing.domain
            if existing and candidate.subtype == "other" and existing.domain
            else candidate.subtype
        )
        definition = _merge_text(
            str(old_metadata.get("definition") or (existing.summary if existing else "") or ""),
            candidate.definition,
        )
        characteristics = _unique(
            [
                *_metadata_strings(old_metadata, "key_characteristics"),
                *candidate.key_characteristics,
            ]
        )
        applications = _unique(
            [*_metadata_strings(old_metadata, "applications"), *candidate.applications]
        )
        related_entities = _unique(
            [
                *_metadata_strings(old_metadata, "related_entities"),
                *candidate.related_entity_names,
            ]
        )
        related_concepts = _unique(
            [
                *_metadata_strings(old_metadata, "related_concepts"),
                *candidate.related_concepts,
            ]
        )
        aliases = _unique(
            [*_metadata_strings(old_metadata, "aliases"), *candidate.aliases]
        )
        mention_entries = [
            *_metadata_mentions(old_metadata),
            *((mention, source_link) for mention in candidate.mentions),
        ]
        mention_entries = list(dict.fromkeys(mention_entries))
        mentions = _unique(quote for quote, _mention_source in mention_entries)
        sources = _unique(
            [*_metadata_strings(old_metadata, "sources"), source_link]
        )
        created = str(old_metadata.get("created") or generated_date)
        metadata: dict[str, object] = {
            "subtype": subtype,
            "aliases": aliases,
            "definition": definition,
            "key_characteristics": characteristics,
            "applications": applications,
            "related_entities": related_entities,
            "related_concepts": related_concepts,
            "mentions": mentions,
            "mention_entries": [
                {"quote": quote, "source": mention_source}
                for quote, mention_source in mention_entries
            ],
            "sources": sources,
            "created": created,
            "updated": generated_date,
        }
        content = render_concept_markdown(
            title=resolved_title,
            subtype=subtype,
            definition=definition,
            key_characteristics=characteristics,
            applications=applications,
            aliases=aliases,
            related_entities=related_entities,
            related_concepts=related_concepts,
            mention_entries=mention_entries,
            source_links=_metadata_strings(old_metadata, "sources"),
            source_link=source_link,
            created=created,
            updated=generated_date,
        )
        plans.append(
            WikiDocumentPlan(
                document_kind="concept",
                document_key=resolved_key,
                file_path=concept_file_path(resolved_key),
                domain=subtype,
                title=resolved_title,
                summary=definition[:_SUMMARY_PREVIEW_CHARS],
                normalized_content=content,
                action="update" if existing else "create",
                metadata=metadata,
            )
        )
        key_by_title[title.casefold()] = resolved_key
        key_by_title[resolved_title.casefold()] = resolved_key
    return plans, key_by_title


def _plan_relations(
    *,
    classification: WikiClassification,
    entity_keys: dict[str, str],
    concept_keys: dict[str, str],
) -> list[WikiRelationPlan]:
    """LLM이 추출한 entity·concept 연결을 DB 관계 계획으로 변환한다."""
    relations: list[WikiRelationPlan] = []
    seen: set[tuple[str, str, str]] = set()

    def append(
        source_key: str,
        source_kind: str,
        target_key: str,
        target_kind: str,
        relation_type: str,
    ) -> None:
        """중복과 자기 참조를 제외하고 관계 하나를 추가한다."""
        signature = (source_key, target_key, relation_type)
        if source_key == target_key or signature in seen:
            return
        seen.add(signature)
        relations.append(
            WikiRelationPlan(
                source_document_key=source_key,
                source_document_kind=source_kind,
                target_document_key=target_key,
                target_document_kind=target_kind,
                relation_type=relation_type,
            )
        )

    for entity in classification.entities:
        source_key = entity_keys.get(entity.name.strip().casefold())
        if not source_key:
            continue
        for related_name in entity.related_entity_names:
            target_key = entity_keys.get(related_name.strip().casefold())
            if target_key:
                append(
                    source_key,
                    "entity",
                    target_key,
                    "entity",
                    "entity_relation",
                )
        for concept_name in entity.related_concepts:
            target_key = concept_keys.get(concept_name.strip().casefold())
            if target_key:
                append(
                    source_key,
                    "entity",
                    target_key,
                    "concept",
                    "applies_concept",
                )
    for concept in classification.concepts:
        source_key = concept_keys.get(concept.title.strip().casefold())
        if not source_key:
            continue
        for related_name in concept.related_concepts:
            target_key = concept_keys.get(related_name.strip().casefold())
            if target_key:
                append(
                    source_key,
                    "concept",
                    target_key,
                    "concept",
                    "related_concept",
                )
        for entity_name in concept.related_entity_names:
            entity_key = entity_keys.get(entity_name.strip().casefold())
            if entity_key:
                append(
                    entity_key,
                    "entity",
                    source_key,
                    "concept",
                    "applies_concept",
                )
    return relations


def _merge_relations(
    existing: Sequence[WikiRelationPlan],
    incoming: Sequence[WikiRelationPlan],
) -> list[WikiRelationPlan]:
    """기존 Wiki 관계를 보존하고 같은 방향의 최신 관계 Metadata를 반영한다."""
    merged: dict[tuple[str, str, str], WikiRelationPlan] = {}
    for relation in [*existing, *incoming]:
        key = (
            relation.source_document_key,
            relation.target_document_key,
            relation.relation_type,
        )
        merged[key] = relation
    return list(merged.values())


def build_wiki_plan(
    *,
    source_title: str,
    source_url: str | None,
    source_tags: Sequence[str],
    source_content_hash: str,
    source_size_bytes: int,
    classification: WikiClassification,
    existing_entities: Sequence[ExistingWikiEntry],
    existing_concepts: Sequence[ExistingWikiEntry],
    generated_at: str,
    model: str,
    existing_relations: Sequence[WikiRelationPlan] = (),
) -> WikiBuildPlan:
    """LLM 분류 결과와 기존 Wiki 상태로 증분 Build 산출물을 만든다."""
    generated_date = generated_at[:10]
    source_path = source_file_path(source_title, source_content_hash)
    source_wiki_link = _source_link(source_path, source_title)
    entity_plans, entity_keys = _plan_entities(
        classification=classification,
        existing_entities=existing_entities,
        source_title=source_title,
        source_link=source_wiki_link,
        generated_date=generated_date,
    )
    concept_plans, concept_keys = _plan_concepts(
        classification=classification,
        existing_concepts=existing_concepts,
        source_link=source_wiki_link,
        generated_date=generated_date,
    )
    relations = _merge_relations(
        existing_relations,
        _plan_relations(
            classification=classification,
            entity_keys=entity_keys,
            concept_keys=concept_keys,
        ),
    )
    merged_entities = _merge_entries("entity", existing_entities, entity_plans)
    merged_concepts = _merge_entries("concept", existing_concepts, concept_plans)
    schema_content = render_schema_markdown(
        entities=merged_entities,
        concepts=merged_concepts,
        relations=relations,
    )
    schema_plan = WikiDocumentPlan(
        document_kind="schema",
        document_key=SCHEMA_DOCUMENT_KEY,
        file_path=SCHEMA_FILE_PATH,
        domain=None,
        title="Schema",
        summary="Namespace entity·concept·관계 요약",
        normalized_content=schema_content,
        action="update",
        metadata={"updated": generated_date},
    )
    source_content = render_source_manifest_markdown(
        source_title=source_title,
        source_url=source_url,
        source_summary=classification.source_summary,
        source_tags=source_tags,
        content_hash=source_content_hash,
        ingested_at=generated_at,
        entity_links=[(plan.document_key, plan.title) for plan in entity_plans],
        concept_links=[(plan.document_key, plan.title) for plan in concept_plans],
    )
    index_content = render_index_markdown(
        entities=merged_entities,
        concepts=merged_concepts,
        source_entries=[(source_path, source_title)],
    )
    all_plans = [*entity_plans, *concept_plans, schema_plan]
    log_content = render_log_entry(
        timestamp=generated_at,
        source_title=source_title,
        model=model,
        source_size_bytes=source_size_bytes,
        created_paths=[plan.file_path for plan in all_plans if plan.action == "create"],
        updated_paths=[plan.file_path for plan in all_plans if plan.action == "update"],
    )
    return WikiBuildPlan(
        entities=entity_plans,
        concepts=concept_plans,
        schema=schema_plan,
        relations=relations,
        index=GeneratedArtifact(file_path="index.md", content=index_content),
        source_manifest=GeneratedArtifact(file_path=source_path, content=source_content),
        log_entry=GeneratedArtifact(file_path="log.md", content=log_content),
    )
