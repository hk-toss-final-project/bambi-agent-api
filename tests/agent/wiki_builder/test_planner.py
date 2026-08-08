"""개인 지식 Wiki Build 계획 조립을 검증한다."""

from agent.wiki_builder.models import (
    ConceptClassification,
    EntityClassification,
    ExistingWikiEntry,
    WikiClassification,
    WikiRelationClassification,
    WikiRelationPlan,
)
from agent.wiki_builder.features.planning import build_wiki_plan


def _plan(
    classification: WikiClassification,
    *,
    existing_entities: list[ExistingWikiEntry] | None = None,
    existing_concepts: list[ExistingWikiEntry] | None = None,
    existing_relations: list[WikiRelationPlan] | None = None,
):
    """공통 원본 Metadata로 Wiki Build 계획을 만든다."""
    return build_wiki_plan(
        source_title="Obsidian 소개",
        source_url="https://example.com/obsidian",
        source_tags=["clippings", "pkm"],
        source_content_hash="abcdef123456",
        source_size_bytes=2048,
        classification=classification,
        existing_entities=existing_entities or [],
        existing_concepts=existing_concepts or [],
        generated_at="2026-07-15T12:00:00+09:00",
        model="gpt-4.1-mini",
        existing_relations=existing_relations or [],
    )


def test_new_entity_becomes_personal_knowledge_document() -> None:
    """새 entity를 subtype·별칭·출처·인용이 있는 문서로 계획한다."""
    classification = WikiClassification(
        entities=[
            EntityClassification(
                name="Obsidian",
                subtype="product",
                description="Markdown 기반 지식 관리 도구다.",
                aliases=["옵시디언"],
                mentions=["Markdown 기반이다."],
            )
        ]
    )

    plan = _plan(classification)

    entity = plan.entities[0]
    assert entity.document_key == "obsidian"
    assert entity.file_path == "entities/obsidian.md"
    assert entity.domain == "product"
    assert entity.action == "create"
    assert entity.metadata["aliases"] == ["옵시디언"]
    assert "type: entity" in entity.normalized_content
    assert "[[sources/obsidian-소개_abcdef|Obsidian 소개]]" in entity.normalized_content


def test_existing_entity_update_preserves_append_only_metadata() -> None:
    """기존 entity의 생성일·별칭·출처·설명을 보존하고 신규 정보를 덧붙인다."""
    existing = [
        ExistingWikiEntry(
            "entity",
            "obsidian",
            "Obsidian",
            "product",
            "기존 설명",
            {
                "created": "2026-07-01",
                "aliases": ["옵시디언"],
                "sources": ["[[sources/old_111111|Old]]"],
                "description": "기존 설명",
            },
        )
    ]
    classification = WikiClassification(
        entities=[
            EntityClassification(
                name="Obsidian App",
                subtype="other",
                description="새 설명",
                aliases=["Obsidian App"],
                matched_existing_key="obsidian",
                is_alias=True,
            )
        ]
    )

    plan = _plan(classification, existing_entities=existing)

    entity = plan.entities[0]
    assert entity.action == "update"
    assert entity.title == "Obsidian"
    assert entity.domain == "product"
    assert entity.metadata["created"] == "2026-07-01"
    assert entity.metadata["aliases"] == ["옵시디언", "Obsidian App"]
    assert "기존 설명" in entity.summary
    assert "새 설명" in entity.summary
    assert "[[sources/old_111111|Old]]" in entity.normalized_content


def test_unknown_matched_key_is_not_trusted_as_document_path() -> None:
    """LLM이 존재하지 않는 matched key를 반환해도 이름에서 안전한 키를 만든다."""
    classification = WikiClassification(
        entities=[
            EntityClassification(
                name="Safe Entity",
                matched_existing_key="../../outside",
            )
        ]
    )

    plan = _plan(classification)

    assert plan.entities[0].document_key == "safe-entity"
    assert plan.entities[0].file_path == "entities/safe-entity.md"


def test_concept_does_not_require_two_related_entities() -> None:
    """재사용 가능한 개인 지식 concept은 관련 entity 개수와 무관하게 생성한다."""
    classification = WikiClassification(
        concepts=[
            ConceptClassification(
                title="연결 노트",
                subtype="method",
                definition="노트를 링크로 연결하는 방법이다.",
                related_entity_names=["Obsidian"],
            )
        ]
    )

    plan = _plan(classification)

    assert len(plan.concepts) == 1
    assert plan.concepts[0].document_key == "연결-노트"
    assert plan.concepts[0].domain == "method"


def test_entity_to_concept_relation_uses_resolved_keys() -> None:
    """검증된 entity·concept 관계 이름을 실제 문서 키와 연결한다."""
    classification = WikiClassification(
        entities=[
            EntityClassification(
                name="Obsidian",
                subtype="product",
            )
        ],
        concepts=[
            ConceptClassification(
                title="연결 노트",
                subtype="method",
                definition="노트 연결 방법",
            )
        ],
        relations=[
            WikiRelationClassification(
                source_name="Obsidian",
                source_kind="entity",
                target_name="연결 노트",
                target_kind="concept",
                relation_type="applies_concept",
                evidence="Obsidian은 연결 노트를 지원한다.",
            )
        ],
    )

    plan = _plan(classification)

    assert len(plan.relations) == 1
    relation = plan.relations[0]
    assert relation.source_document_key == "obsidian"
    assert relation.target_document_key == "연결-노트"
    assert relation.relation_type == "applies_concept"
    assert relation.metadata["evidence"] == "Obsidian은 연결 노트를 지원한다."
    assert plan.extracted_relation_count == 1
    assert plan.isolated_node_count == 0


def test_entity_relation_is_created_when_both_entities_exist() -> None:
    """원문이 연결한 두 entity가 존재하면 entity_relation을 계획한다."""
    classification = WikiClassification(
        entities=[
            EntityClassification(name="Obsidian"),
            EntityClassification(name="Obsidian Web Clipper"),
        ],
        relations=[
            WikiRelationClassification(
                source_name="Obsidian Web Clipper",
                source_kind="entity",
                target_name="Obsidian",
                target_kind="entity",
                relation_type="entity_relation",
                evidence="Web Clipper는 Obsidian에 저장한다.",
            )
        ],
    )

    plan = _plan(classification)

    assert any(relation.relation_type == "entity_relation" for relation in plan.relations)


def test_relation_uses_matched_existing_key_when_alias_name_changes() -> None:
    """관계 노드가 별칭으로 분류돼도 검증된 기존 문서 키로 연결한다."""
    existing = [
        ExistingWikiEntry(
            "entity",
            "obsidian",
            "Obsidian",
            "product",
            "지식 관리 도구",
        )
    ]
    classification = WikiClassification(
        entities=[
            EntityClassification(
                name="옵시디언",
                matched_existing_key="obsidian",
                is_alias=True,
            ),
            EntityClassification(name="Obsidian Web Clipper"),
        ],
        relations=[
            WikiRelationClassification(
                source_name="Obsidian Web Clipper",
                source_kind="entity",
                target_name="옵시디언",
                target_kind="entity",
                relation_type="entity_relation",
                evidence="Web Clipper는 옵시디언에 저장한다.",
                target_matched_key="obsidian",
            )
        ],
    )

    plan = _plan(classification, existing_entities=existing)

    assert len(plan.relations) == 1
    assert plan.relations[0].source_document_key == "obsidian-web-clipper"
    assert plan.relations[0].target_document_key == "obsidian"


def test_concept_relations_include_related_concepts_and_entities() -> None:
    """concept에서 선언한 관련 concept과 entity도 DB 관계 계획에 반영한다."""
    classification = WikiClassification(
        entities=[EntityClassification(name="Obsidian")],
        concepts=[
            ConceptClassification(title="연결 노트"),
            ConceptClassification(title="개인 지식 관리"),
        ],
        relations=[
            WikiRelationClassification(
                source_name="Obsidian",
                source_kind="entity",
                target_name="연결 노트",
                target_kind="concept",
                relation_type="applies_concept",
                evidence="Obsidian은 연결 노트를 사용한다.",
            ),
            WikiRelationClassification(
                source_name="연결 노트",
                source_kind="concept",
                target_name="개인 지식 관리",
                target_kind="concept",
                relation_type="related_concept",
                evidence="연결 노트는 개인 지식 관리 방법이다.",
            ),
        ],
    )

    plan = _plan(classification)

    signatures = {
        (
            relation.source_document_kind,
            relation.source_document_key,
            relation.target_document_kind,
            relation.target_document_key,
            relation.relation_type,
        )
        for relation in plan.relations
    }
    assert (
        "concept",
        "연결-노트",
        "concept",
        "개인-지식-관리",
        "related_concept",
    ) in signatures
    assert (
        "entity",
        "obsidian",
        "concept",
        "연결-노트",
        "applies_concept",
    ) in signatures


def test_existing_relations_remain_in_schema_snapshot() -> None:
    """새 원본에 언급되지 않은 기존 관계도 새 Schema Snapshot에서 보존한다."""
    existing_relation = WikiRelationPlan(
        source_document_key="obsidian",
        source_document_kind="entity",
        target_document_key="연결-노트",
        target_document_kind="concept",
        relation_type="applies_concept",
    )

    plan = _plan(WikiClassification(), existing_relations=[existing_relation])

    assert plan.relations == [existing_relation]
    assert "[[entities/obsidian]] --applies_concept-->" in plan.schema.normalized_content


def test_schema_uses_database_root_key() -> None:
    """Schema 문서 키와 경로가 DB CHECK 제약과 일치한다."""
    plan = _plan(WikiClassification())

    assert plan.schema.document_key == "root"
    assert plan.schema.file_path == "schema/schema.md"


def test_plan_counts_nodes_without_validated_relations_as_isolated() -> None:
    """검증된 관계가 없는 entity·concept를 고립 노드로 집계한다."""
    classification = WikiClassification(
        entities=[EntityClassification(name="Obsidian")],
        concepts=[ConceptClassification(title="개인 지식 관리")],
        relation_warnings=["검증된 관계 없음"],
    )

    plan = _plan(classification)

    assert plan.extracted_relation_count == 0
    assert plan.isolated_node_count == 2
    assert plan.relation_warnings == ["검증된 관계 없음"]


def test_source_manifest_uses_content_hash_suffix_and_source_tags() -> None:
    """source 파일은 Hash 접미사로 충돌을 막고 원본 태그를 상속한다."""
    plan = _plan(WikiClassification(source_summary="원본 요약"))

    assert plan.source_manifest.file_path == "sources/obsidian-소개_abcdef.md"
    assert 'tags: ["clippings", "pkm"]' in plan.source_manifest.content
    assert "원본 요약" in plan.source_manifest.content


def test_index_and_log_use_vault_artifact_paths() -> None:
    """index와 log가 생성된 문서의 풀 경로와 ingest Metadata를 포함한다."""
    classification = WikiClassification(
        entities=[EntityClassification(name="Obsidian", subtype="product")]
    )

    plan = _plan(classification)

    assert "[[entities/obsidian|Obsidian]]" in plan.index.content
    assert "gpt-4.1-mini · 2.0KB" in plan.log_entry.content
    assert "[[entities/obsidian]]" in plan.log_entry.content


def test_node_role_is_recorded_for_interest_candidates() -> None:
    """원문에서 도구로 쓰인 노드는 관심 후보 표시가 붙지 않는다.

    이 표시가 없으면 DBeaver 같은 도구가 연결 수만으로 관심사 1위가 된다
    (2026-08-07 실측).
    """
    classification = WikiClassification(
        entities=[
            EntityClassification(name="PostgreSQL", subtype="product", role="subject"),
            EntityClassification(name="DBeaver", subtype="product", role="tool"),
        ],
        concepts=[
            ConceptClassification(title="인덱스 튜닝", subtype="method", role="subject"),
            ConceptClassification(title="API 키 발급", subtype="method", role="mention"),
        ],
    )

    plan = _plan(classification)

    roles = {node.title: node.metadata["interest_subject"] for node in plan.entities}
    roles.update(
        {node.title: node.metadata["interest_subject"] for node in plan.concepts}
    )
    assert roles == {
        "PostgreSQL": True,
        "DBeaver": False,
        "인덱스 튜닝": True,
        "API 키 발급": False,
    }


def test_node_stays_an_interest_once_it_was_a_subject() -> None:
    """한 번 주제였던 노드는 뒤에 도구로 쓰여도 관심 후보로 남는다.

    같은 노드가 글마다 역할이 다르다. 사용자가 그 대상을 다룬 글을 저장한 적이
    있다는 사실은 뒤에 오는 글이 지울 수 없다.
    """
    existing = [
        ExistingWikiEntry(
            "entity",
            "dbeaver",
            "DBeaver",
            "product",
            "기존 설명",
            {"created": "2026-07-01", "interest_subject": True},
        )
    ]
    classification = WikiClassification(
        entities=[
            EntityClassification(
                name="DBeaver",
                subtype="product",
                role="tool",
                matched_existing_key="dbeaver",
            )
        ]
    )

    plan = _plan(classification, existing_entities=existing)

    assert plan.entities[0].metadata["interest_subject"] is True
