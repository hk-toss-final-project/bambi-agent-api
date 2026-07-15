"""agent/wiki_builder/planner.py를 검증한다. LLM·DB 호출 없는 순수 함수 테스트."""

from agent.wiki_builder.models import (
    ConceptClassification,
    EntityClassification,
    ExistingWikiEntry,
    WikiClassification,
)
from agent.wiki_builder.planner import build_wiki_plan


def _plan(classification: WikiClassification, existing_entities=(), existing_concepts=()):
    return build_wiki_plan(
        source_title="클리핑: pgvector 소개",
        source_url="https://example.com/pgvector",
        classification=classification,
        existing_entities=list(existing_entities),
        existing_concepts=list(existing_concepts),
        generated_at="2026-07-15T00:00:00+09:00",
    )


def test_new_entity_without_match_is_created_with_slugified_key() -> None:
    """기존 entity와 매칭되지 않으면 새 document_key로 create 계획을 만든다."""
    classification = WikiClassification(
        entities=[EntityClassification(name="wiki_documents", domain="지식 문서", role="Head 관리")]
    )

    plan = _plan(classification)

    assert len(plan.entities) == 1
    entity = plan.entities[0]
    assert entity.document_key == "wiki-documents"
    assert entity.file_path == "entities/wiki-documents.md"
    assert entity.action == "create"
    assert entity.title == "wiki_documents"


def test_entity_alias_updates_existing_and_notes_synonym() -> None:
    """is_alias=True + matched_existing_key면 새 문서를 만들지 않고 기존 문서를 갱신한다."""
    existing = [ExistingWikiEntry("entity", "wiki-documents", "Wiki Documents", "지식 문서", "기존 요약")]
    classification = WikiClassification(
        entities=[
            EntityClassification(
                name="위키 문서",
                domain="",
                role="같은 대상을 가리킴",
                matched_existing_key="wiki-documents",
                is_alias=True,
            )
        ]
    )

    plan = _plan(classification, existing_entities=existing)

    assert len(plan.entities) == 1
    entity = plan.entities[0]
    assert entity.document_key == "wiki-documents"
    assert entity.action == "update"
    assert entity.title == "Wiki Documents"  # 기존 제목을 유지
    assert "동의어: 위키 문서" in entity.normalized_content
    assert entity.domain == "지식 문서"  # 후보에 domain이 없으면 기존 값을 물려받음


def test_entity_without_name_is_skipped() -> None:
    """이름이 빈 entity 후보는 계획에 포함하지 않는다."""
    classification = WikiClassification(entities=[EntityClassification(name="   ", domain="x", role="x")])

    plan = _plan(classification)

    assert plan.entities == []


def test_new_concept_requires_at_least_two_related_entities() -> None:
    """관련 entity가 1개뿐인 신규 concept 후보는 규칙서 기준에 따라 만들지 않는다."""
    classification = WikiClassification(
        concepts=[
            ConceptClassification(
                title="단일 엔티티 패턴",
                summary="요약",
                explanation="설명",
                related_entity_names=["wiki_documents"],
            )
        ]
    )

    plan = _plan(classification)

    assert plan.concepts == []


def test_new_concept_with_two_related_entities_is_created() -> None:
    """관련 entity가 2개 이상이면 concept 자격을 만족해 새로 생성한다."""
    classification = WikiClassification(
        concepts=[
            ConceptClassification(
                title="Versioned Configuration",
                summary="덮어쓰지 않고 새 버전을 추가한다.",
                explanation="이력 보존을 위해서다.",
                related_entity_names=["prompt_templates", "model_configs"],
            )
        ]
    )

    plan = _plan(classification)

    assert len(plan.concepts) == 1
    concept = plan.concepts[0]
    assert concept.document_key == "versioned-configuration"
    assert concept.action == "create"
    assert "prompt_templates" in concept.normalized_content


def test_concept_update_is_allowed_even_with_fewer_than_two_related_entities() -> None:
    """이미 있는 concept의 갱신이면 관련 entity 수 제약을 적용하지 않는다."""
    existing = [ExistingWikiEntry("concept", "versioned-configuration", "Versioned Configuration", None, "기존 요약")]
    classification = WikiClassification(
        concepts=[
            ConceptClassification(
                title="Versioned Configuration",
                summary="갱신된 요약",
                explanation="갱신된 설명",
                related_entity_names=["prompt_templates"],
                matched_existing_key="versioned-configuration",
            )
        ]
    )

    plan = _plan(classification, existing_concepts=existing)

    assert len(plan.concepts) == 1
    assert plan.concepts[0].action == "update"
    assert plan.concepts[0].title == "Versioned Configuration"


def test_relations_link_entity_to_matching_concept_by_title() -> None:
    """entity의 related_concepts 이름이 실제 concept과 매칭되면 관계를 만든다."""
    classification = WikiClassification(
        entities=[
            EntityClassification(
                name="prompt_templates",
                domain="설정",
                role="Prompt 식별자 관리",
                related_concepts=["Versioned Configuration"],
            )
        ],
        concepts=[
            ConceptClassification(
                title="Versioned Configuration",
                summary="요약",
                explanation="설명",
                related_entity_names=["prompt_templates", "model_configs"],
            )
        ],
    )

    plan = _plan(classification)

    assert len(plan.relations) == 1
    relation = plan.relations[0]
    assert relation.source_document_key == "prompt-templates"
    assert relation.target_document_key == "versioned-configuration"
    assert relation.relation_type == "applies_concept"


def test_relations_skip_unmatched_concept_names() -> None:
    """실제로 만들어지지 않은 concept 이름을 가리키면 관계를 만들지 않는다."""
    classification = WikiClassification(
        entities=[
            EntityClassification(
                name="prompt_templates",
                domain="설정",
                role="역할",
                related_concepts=["존재하지 않는 개념"],
            )
        ]
    )

    plan = _plan(classification)

    assert plan.relations == []


def test_schema_and_index_include_untouched_existing_entries() -> None:
    """이번 Build와 무관한 기존 entity·concept도 schema·index에 계속 포함된다."""
    existing_entities = [ExistingWikiEntry("entity", "other-entity", "Other Entity", "기타", None)]
    classification = WikiClassification(
        entities=[EntityClassification(name="wiki_documents", domain="지식 문서", role="역할")]
    )

    plan = _plan(classification, existing_entities=existing_entities)

    assert "[[other-entity]] Other Entity" in plan.schema.normalized_content
    assert "[[wiki-documents]] wiki_documents" in plan.schema.normalized_content
    assert "[[other-entity]] Other Entity" in plan.index.content
    assert "[[wiki-documents]] wiki_documents" in plan.index.content


def test_schema_plan_has_fixed_key_and_path() -> None:
    """schema 문서는 항상 같은 document_key와 file_path를 갖는다(Namespace당 1개)."""
    plan = _plan(WikiClassification())

    assert plan.schema.document_key == "schema"
    assert plan.schema.file_path == "schema/schema.md"
    assert plan.schema.document_kind == "schema"


def test_log_entry_reports_created_and_updated_counts() -> None:
    """log 항목이 생성·갱신된 entity·concept 이름과 schema 재생성 여부를 담는다."""
    classification = WikiClassification(
        entities=[EntityClassification(name="wiki_documents", domain="지식 문서", role="역할")],
        concepts=[
            ConceptClassification(
                title="Versioned Configuration",
                summary="요약",
                explanation="설명",
                related_entity_names=["a", "b"],
            )
        ],
    )

    plan = _plan(classification)

    assert "entity 생성: wiki_documents" in plan.log_entry.content
    assert "concept 생성: Versioned Configuration" in plan.log_entry.content
    assert "schema 재생성: 예" in plan.log_entry.content


def test_log_entry_notes_no_schema_regeneration_when_nothing_changed() -> None:
    """entity·concept 변화가 전혀 없으면 schema 재생성 여부를 '아니오'로 남긴다."""
    plan = _plan(WikiClassification())

    assert "schema 재생성: 아니오" in plan.log_entry.content


def test_source_manifest_uses_slugified_source_title_as_path() -> None:
    """sources/ 산출물 경로는 원본 제목을 slug로 바꾼 이름을 쓴다."""
    plan = _plan(WikiClassification())

    assert plan.source_manifest.file_path == "sources/클리핑-pgvector-소개.md"
    assert "https://example.com/pgvector" in plan.source_manifest.content
