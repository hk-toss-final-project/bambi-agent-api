"""개인 Wiki identity 표기 정규화와 후보 탐색을 검증한다."""

from agent.wiki_builder.features.identity_resolution import (
    normalize_wiki_surface,
    prepare_wiki_identity_resolution,
)
from shared.wiki_models import (
    ConceptClassification,
    EntityClassification,
    ExistingWikiEntry,
    WikiClassification,
)


def _entry(
    document_kind: str,
    document_key: str,
    title: str,
    *,
    aliases: list[str] | None = None,
) -> ExistingWikiEntry:
    """테스트용 기존 Wiki 문서를 만든다."""
    return ExistingWikiEntry(
        document_kind=document_kind,
        document_key=document_key,
        title=title,
        domain="term",
        summary=None,
        metadata={"aliases": aliases or []},
    )


def test_normalize_wiki_surface_ignores_spacing_punctuation_and_case() -> None:
    """띄어쓰기·구두점·영문 대소문자 차이는 같은 비교 키가 된다."""
    assert normalize_wiki_surface(" Machine-Learning ") == "machinelearning"
    assert normalize_wiki_surface("머신 러닝") == "머신러닝"
    assert normalize_wiki_surface("ＡＩ") == "ai"


def test_prepare_resolution_matches_spacing_variant_to_existing_concept() -> None:
    """머신러닝 표기를 기존 머신 러닝 Concept에 LLM 없이 연결한다."""
    draft = prepare_wiki_identity_resolution(
        classification=WikiClassification(
            concepts=[ConceptClassification(title="머신러닝")]
        ),
        existing_entities=[],
        existing_concepts=[_entry("concept", "머신-러닝", "머신 러닝")],
    )

    assert draft.conflicts == ()
    assert len(draft.classification.concepts) == 1
    concept = draft.classification.concepts[0]
    assert concept.matched_existing_key == "머신-러닝"
    assert concept.overlaps_existing is True
    assert concept.aliases == ["머신러닝"]


def test_prepare_resolution_matches_translation_through_alias() -> None:
    """기존 별칭에 등록된 영문 표기를 같은 한국어 Concept에 연결한다."""
    draft = prepare_wiki_identity_resolution(
        classification=WikiClassification(
            concepts=[ConceptClassification(title="Machine Learning")]
        ),
        existing_entities=[],
        existing_concepts=[
            _entry(
                "concept",
                "머신-러닝",
                "머신 러닝",
                aliases=["machine learning"],
            )
        ],
    )

    concept = draft.classification.concepts[0]
    assert draft.conflicts == ()
    assert concept.matched_existing_key == "머신-러닝"
    assert concept.aliases == ["Machine Learning"]


def test_prepare_resolution_merges_same_kind_variants_in_one_build() -> None:
    """한 Build에 함께 나온 동일 kind 표기 변형을 한 후보로 병합한다."""
    draft = prepare_wiki_identity_resolution(
        classification=WikiClassification(
            concepts=[
                ConceptClassification(title="머신 러닝", definition="첫 설명"),
                ConceptClassification(title="머신러닝", definition="둘째 설명"),
            ]
        ),
        existing_entities=[],
        existing_concepts=[],
    )

    assert draft.conflicts == ()
    assert len(draft.classification.concepts) == 1
    assert draft.classification.concepts[0].title == "머신 러닝"
    assert draft.classification.concepts[0].aliases == ["머신러닝"]
    assert "첫 설명" in draft.classification.concepts[0].definition
    assert "둘째 설명" in draft.classification.concepts[0].definition


def test_prepare_resolution_defers_cross_kind_collision() -> None:
    """같은 표기가 entity와 concept에 걸치면 임의 선택하지 않고 충돌로 남긴다."""
    draft = prepare_wiki_identity_resolution(
        classification=WikiClassification(
            entities=[EntityClassification(name="머신러닝")],
        ),
        existing_entities=[],
        existing_concepts=[_entry("concept", "머신-러닝", "머신 러닝")],
    )

    assert len(draft.conflicts) == 1
    conflict = draft.conflicts[0]
    assert conflict.incoming_refs == ("entity:0",)
    assert conflict.incoming_kinds == ("entity",)
    assert [(option.document_kind, option.document_key) for option in conflict.options] == [
        ("concept", "머신-러닝")
    ]
    assert draft.classification.entities[0].matched_existing_key is None


def test_prepare_resolution_defers_duplicate_existing_namespaces() -> None:
    """같은 표면형이 기존 entity·concept 모두에 있으면 모호한 후보를 모두 보존한다."""
    draft = prepare_wiki_identity_resolution(
        classification=WikiClassification(
            concepts=[ConceptClassification(title="머신러닝")]
        ),
        existing_entities=[_entry("entity", "머신-러닝", "머신 러닝")],
        existing_concepts=[_entry("concept", "머신-러닝", "머신 러닝")],
    )

    assert len(draft.conflicts) == 1
    assert {
        (option.document_kind, option.document_key)
        for option in draft.conflicts[0].options
    } == {("entity", "머신-러닝"), ("concept", "머신-러닝")}


def test_prepare_resolution_defers_cross_kind_nodes_created_together() -> None:
    """분류기가 같은 이름을 entity·concept로 동시에 만들면 의미 판정 대상으로 묶는다."""
    draft = prepare_wiki_identity_resolution(
        classification=WikiClassification(
            entities=[EntityClassification(name="Machine Learning")],
            concepts=[ConceptClassification(title="machine-learning")],
        ),
        existing_entities=[],
        existing_concepts=[],
    )

    assert len(draft.conflicts) == 1
    assert set(draft.conflicts[0].incoming_refs) == {"entity:0", "concept:0"}
    assert draft.conflicts[0].options == ()
