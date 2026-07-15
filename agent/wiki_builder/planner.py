"""LLM 분류 결과 -> WikiBuildPlan 조립.

llm_wiki.classify_source_for_wiki의 결과와 Namespace의 기존 entity·concept
목록을 Agent DB Wiki 생성 규칙서의 신규/갱신/중복 판단 기준으로 병합해, 저장까지
바로 이어질 수 있는 WikiBuildPlan(entities, concepts, schema, relations, index,
sources, log)을 만든다. LLM이나 DB를 직접 호출하지 않는 순수 함수다.
"""

from __future__ import annotations

from collections.abc import Sequence

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
)

# 요약 미리보기에 담을 최대 문자 수. wiki_document_versions.summary는 전체 본문이
# 아니라 검색 Preview용이므로 짧게 자른다.
_SUMMARY_PREVIEW_CHARS = 280

# concept 자격 최소 관련 entity 수. 규칙서: entity 1개에만 해당하면 concept으로
# 만들지 않고 해당 entity 문서 안에만 기록한다. LLM이 이 규칙을 놓쳐도 코드에서
# 한 번 더 강제한다.
_MIN_RELATED_ENTITIES_FOR_NEW_CONCEPT = 2


def _merge_entries(
    document_kind: str,
    existing: Sequence[ExistingWikiEntry],
    plans: Sequence[WikiDocumentPlan],
) -> list[ExistingWikiEntry]:
    """기존 목록에 이번 Build로 생성·갱신된 문서를 반영한 Namespace 전체 목록을 만든다."""
    merged: dict[str, ExistingWikiEntry] = {entry.document_key: entry for entry in existing}
    for plan in plans:
        merged[plan.document_key] = ExistingWikiEntry(
            document_kind=document_kind,
            document_key=plan.document_key,
            title=plan.title,
            domain=plan.domain,
            summary=plan.summary,
        )
    return list(merged.values())


def _plan_entities(
    classification: WikiClassification,
    existing_entities: Sequence[ExistingWikiEntry],
    source_title: str,
) -> tuple[list[WikiDocumentPlan], dict[str, str]]:
    """entity 후보를 신규/갱신 문서 계획으로 변환하고, 이름->document_key 매핑을 함께 만든다."""
    existing_by_key = {entry.document_key: entry for entry in existing_entities}
    plans: list[WikiDocumentPlan] = []
    key_by_name: dict[str, str] = {}

    for candidate in classification.entities:
        name = candidate.name.strip()
        if not name:
            continue

        resolved_key = candidate.matched_existing_key or slugify(name)
        existing_entry = existing_by_key.get(resolved_key)
        is_update = existing_entry is not None

        role = candidate.role or "(설명 없음)"
        if candidate.is_alias and candidate.matched_existing_key:
            role = f"{role}\n\n(동의어: {name})" if candidate.role else f"(동의어: {name})"

        domain = candidate.domain
        if is_update and not candidate.domain and existing_entry is not None:
            domain = existing_entry.domain or "미분류"

        title = existing_entry.title if existing_entry is not None else name
        content = render_entity_markdown(
            name=title,
            domain=domain,
            role=role,
            columns=candidate.columns,
            relations=candidate.relations,
            related_concepts=candidate.related_concepts,
            source_titles=[source_title],
        )
        plans.append(
            WikiDocumentPlan(
                document_kind="entity",
                document_key=resolved_key,
                file_path=entity_file_path(resolved_key),
                domain=domain,
                title=title,
                summary=role[:_SUMMARY_PREVIEW_CHARS],
                normalized_content=content,
                action="update" if is_update else "create",
            )
        )
        key_by_name[name.lower()] = resolved_key

    return plans, key_by_name


def _plan_concepts(
    classification: WikiClassification,
    existing_concepts: Sequence[ExistingWikiEntry],
    source_title: str,
) -> tuple[list[WikiDocumentPlan], dict[str, str]]:
    """concept 후보 중 규칙서 자격 기준을 만족하는 것만 신규/갱신 문서 계획으로 변환한다."""
    existing_by_key = {entry.document_key: entry for entry in existing_concepts}
    plans: list[WikiDocumentPlan] = []
    key_by_title: dict[str, str] = {}

    for candidate in classification.concepts:
        title = candidate.title.strip()
        if not title:
            continue
        # 이미 알려진 concept의 갱신이 아니라면, 최소 2개 이상의 entity가 공유해야 concept 자격이 있다.
        if not candidate.matched_existing_key and len(candidate.related_entity_names) < _MIN_RELATED_ENTITIES_FOR_NEW_CONCEPT:
            continue

        resolved_key = candidate.matched_existing_key or slugify(title)
        existing_entry = existing_by_key.get(resolved_key)
        is_update = existing_entry is not None
        resolved_title = existing_entry.title if existing_entry is not None else title

        summary = candidate.summary or "(요약 없음)"
        content = render_concept_markdown(
            title=resolved_title,
            summary=summary,
            explanation=candidate.explanation or "(설명 없음)",
            related_entities=candidate.related_entity_names,
            related_concepts=[],
            source_titles=[source_title],
        )
        plans.append(
            WikiDocumentPlan(
                document_kind="concept",
                document_key=resolved_key,
                file_path=concept_file_path(resolved_key),
                domain=None,
                title=resolved_title,
                summary=summary[:_SUMMARY_PREVIEW_CHARS],
                normalized_content=content,
                action="update" if is_update else "create",
            )
        )
        key_by_title[title.lower()] = resolved_key

    return plans, key_by_title


def _plan_relations(
    classification: WikiClassification,
    entity_key_by_name: dict[str, str],
    existing_concepts: Sequence[ExistingWikiEntry],
    concept_key_by_title: dict[str, str],
) -> list[WikiRelationPlan]:
    """entity가 적용한다고 밝힌 concept 이름을 실제 concept document_key와 연결한다."""
    concept_key_by_lower_title = {
        **{entry.title.strip().lower(): entry.document_key for entry in existing_concepts},
        **concept_key_by_title,
    }

    relations: list[WikiRelationPlan] = []
    seen: set[tuple[str, str, str]] = set()
    for candidate in classification.entities:
        source_key = entity_key_by_name.get(candidate.name.strip().lower())
        if source_key is None:
            continue
        for concept_name in candidate.related_concepts:
            target_key = concept_key_by_lower_title.get(concept_name.strip().lower())
            if target_key is None or target_key == source_key:
                continue
            signature = (source_key, target_key, "applies_concept")
            if signature in seen:
                continue
            seen.add(signature)
            relations.append(
                WikiRelationPlan(
                    source_document_key=source_key,
                    source_document_kind="entity",
                    target_document_key=target_key,
                    target_document_kind="concept",
                    relation_type="applies_concept",
                )
            )
    return relations


def build_wiki_plan(
    *,
    source_title: str,
    source_url: str | None,
    classification: WikiClassification,
    existing_entities: Sequence[ExistingWikiEntry],
    existing_concepts: Sequence[ExistingWikiEntry],
    generated_at: str,
) -> WikiBuildPlan:
    """LLM 분류 결과와 기존 Wiki 상태를 병합해 한 번의 Build 산출물 전체를 만든다.

    Args:
        source_title: 이번 Build의 원천이 된 user_source_document_versions.title
        source_url: 이번 Build의 원천 canonical_url (있으면)
        classification: llm_wiki.classify_source_for_wiki의 결과
        existing_entities: Namespace에 이미 있는 entity 전체 목록
        existing_concepts: Namespace에 이미 있는 concept 전체 목록
        generated_at: index.md에 남길 생성 시각 문자열(ISO 8601 권장)

    Returns:
        저장 계층이 그대로 사용할 수 있는 WikiBuildPlan
    """
    entity_plans, entity_key_by_name = _plan_entities(classification, existing_entities, source_title)
    concept_plans, concept_key_by_title = _plan_concepts(classification, existing_concepts, source_title)
    relations = _plan_relations(classification, entity_key_by_name, existing_concepts, concept_key_by_title)

    merged_entities = _merge_entries("entity", existing_entities, entity_plans)
    merged_concepts = _merge_entries("concept", existing_concepts, concept_plans)

    schema_content = render_schema_markdown(
        entities=merged_entities, concepts=merged_concepts, relations=relations
    )
    schema_plan = WikiDocumentPlan(
        document_kind="schema",
        document_key=SCHEMA_DOCUMENT_KEY,
        file_path=SCHEMA_FILE_PATH,
        domain=None,
        title="Schema",
        summary="Namespace 전체 entity·concept·관계 요약",
        normalized_content=schema_content,
        action="update",
    )

    index_content = render_index_markdown(
        entities=merged_entities,
        concepts=merged_concepts,
        source_titles=[source_title],
        generated_at=generated_at,
    )
    source_manifest_content = render_source_manifest_markdown(
        source_title=source_title,
        source_url=source_url,
        entity_titles=[plan.title for plan in entity_plans],
        concept_titles=[plan.title for plan in concept_plans],
    )
    log_entry_content = render_log_entry(
        timestamp=generated_at,
        source_title=source_title,
        created_entities=[plan.title for plan in entity_plans if plan.action == "create"],
        updated_entities=[plan.title for plan in entity_plans if plan.action == "update"],
        created_concepts=[plan.title for plan in concept_plans if plan.action == "create"],
        updated_concepts=[plan.title for plan in concept_plans if plan.action == "update"],
        schema_regenerated=bool(entity_plans or concept_plans),
    )

    return WikiBuildPlan(
        entities=entity_plans,
        concepts=concept_plans,
        schema=schema_plan,
        relations=relations,
        index=GeneratedArtifact(file_path="index.md", content=index_content),
        source_manifest=GeneratedArtifact(
            file_path=f"sources/{slugify(source_title)}.md", content=source_manifest_content
        ),
        log_entry=GeneratedArtifact(file_path="log/build.log", content=log_entry_content),
    )
