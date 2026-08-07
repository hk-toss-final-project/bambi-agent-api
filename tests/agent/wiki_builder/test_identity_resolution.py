"""개인 Wiki identity 표기 정규화와 후보 탐색을 검증한다."""

import json

import pytest

from agent.wiki_builder.features.identity_resolution import (
    normalize_wiki_surface,
    prepare_wiki_identity_resolution,
    resolve_wiki_identity_conflicts,
)
from agent.llm.api import LlmCompletion
from shared.wiki_models import (
    ConceptClassification,
    EntityClassification,
    ExistingWikiEntry,
    WikiClassification,
    WikiRelationClassification,
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


def _completion(payload: dict[str, object]) -> LlmCompletion:
    """테스트 판정 JSON을 토큰 사용량이 있는 LLM 결과로 감싼다."""
    return LlmCompletion(
        text=json.dumps(payload, ensure_ascii=False),
        model="test-resolver",
        input_tokens=120,
        output_tokens=30,
    )


def test_resolver_skips_llm_when_surface_match_is_deterministic() -> None:
    """충돌이 없으면 추가 LLM 호출 없이 정규화 결과를 확정한다."""
    draft = prepare_wiki_identity_resolution(
        classification=WikiClassification(
            concepts=[ConceptClassification(title="머신러닝")]
        ),
        existing_entities=[],
        existing_concepts=[_entry("concept", "머신-러닝", "머신 러닝")],
    )

    def fail_completion(*args: object, **kwargs: object) -> LlmCompletion:
        """결정적 경로에서 호출되면 테스트를 실패시킨다."""
        raise AssertionError("LLM을 호출하면 안 됩니다.")

    result = resolve_wiki_identity_conflicts(
        draft=draft,
        source_title="머신러닝 소개",
        model="test-model",
        completion=fail_completion,
    )

    assert result.model == "deterministic:wiki-surface-v1"
    assert result.resolved_conflict_count == 0
    assert result.input_tokens == 0


def test_resolver_retypes_entity_and_matches_existing_concept() -> None:
    """의미 판정이 entity 후보를 기존 Concept identity로 재분류해 연결한다."""
    draft = prepare_wiki_identity_resolution(
        classification=WikiClassification(
            source_summary="머신러닝은 데이터에서 패턴을 학습하는 분야다.",
            entities=[
                EntityClassification(
                    name="머신러닝",
                    description="데이터에서 패턴을 학습하는 분야",
                    mentions=["머신러닝은 데이터에서 패턴을 학습한다"],
                )
            ],
        ),
        existing_entities=[],
        existing_concepts=[_entry("concept", "머신-러닝", "머신 러닝")],
    )
    captured: dict[str, object] = {}

    def fake_completion(
        system_prompt: str,
        user_prompt: str,
        **kwargs: object,
    ) -> LlmCompletion:
        """입력을 기록하고 기존 Concept 선택을 반환한다."""
        captured["system"] = system_prompt
        captured["user"] = user_prompt
        captured.update(kwargs)
        return _completion(
            {
                "resolutions": [
                    {
                        "conflict_id": draft.conflicts[0].conflict_id,
                        "action": "match_existing",
                        "target_kind": "concept",
                        "target_key": "머신-러닝",
                    }
                ]
            }
        )

    result = resolve_wiki_identity_conflicts(
        draft=draft,
        source_title="머신러닝 소개",
        model="test-model",
        completion=fake_completion,
    )

    assert result.classification.entities == []
    assert len(result.classification.concepts) == 1
    concept = result.classification.concepts[0]
    assert concept.title == "머신 러닝"
    assert concept.matched_existing_key == "머신-러닝"
    assert concept.aliases == ["머신러닝"]
    assert concept.definition == "데이터에서 패턴을 학습하는 분야"
    assert result.model == "test-resolver"
    assert (result.input_tokens, result.output_tokens) == (120, 30)
    assert captured["model"] == "test-model"
    assert captured["temperature"] == 0
    assert "existing_options" in str(captured["user"])
    assert "보류하거나 누락하지 않는다" in str(captured["system"])


def test_resolver_merges_cross_kind_new_nodes_into_selected_kind() -> None:
    """기존 대상이 없는 entity·concept 충돌은 선택한 kind의 새 노드 하나가 된다."""
    draft = prepare_wiki_identity_resolution(
        classification=WikiClassification(
            entities=[EntityClassification(name="Machine Learning", description="E")],
            concepts=[
                ConceptClassification(
                    title="machine-learning",
                    subtype="field",
                    definition="C",
                )
            ],
        ),
        existing_entities=[],
        existing_concepts=[],
    )

    result = resolve_wiki_identity_conflicts(
        draft=draft,
        source_title="ML",
        model="test-model",
        completion=lambda *args, **kwargs: _completion(
            {
                "resolutions": [
                    {
                        "conflict_id": draft.conflicts[0].conflict_id,
                        "action": "create",
                        "target_kind": "concept",
                        "target_key": None,
                        "canonical_label": "machine-learning",
                    }
                ]
            }
        ),
    )

    assert result.classification.entities == []
    concept = result.classification.concepts[0]
    assert concept.title == "machine-learning"
    assert concept.subtype == "field"
    assert concept.aliases == ["Machine Learning"]
    assert "E" in concept.definition and "C" in concept.definition


def test_resolver_rewrites_relations_and_drops_canonical_self_relation() -> None:
    """충돌 노드를 합친 뒤 생기는 canonical 자기 관계를 저장 후보에서 제거한다."""
    draft = prepare_wiki_identity_resolution(
        classification=WikiClassification(
            entities=[EntityClassification(name="머신러닝")],
            concepts=[ConceptClassification(title="머신 러닝")],
            relations=[
                WikiRelationClassification(
                    source_name="머신러닝",
                    source_kind="entity",
                    target_name="머신 러닝",
                    target_kind="concept",
                    relation_type="applies_concept",
                    evidence="머신러닝",
                )
            ],
        ),
        existing_entities=[],
        existing_concepts=[],
    )

    result = resolve_wiki_identity_conflicts(
        draft=draft,
        source_title="머신러닝",
        model="test-model",
        completion=lambda *args, **kwargs: _completion(
            {
                "resolutions": [
                    {
                        "conflict_id": draft.conflicts[0].conflict_id,
                        "action": "create",
                        "target_kind": "concept",
                        "target_key": None,
                        "canonical_label": "머신 러닝",
                    }
                ]
            }
        ),
    )

    assert result.classification.relations == []


def test_resolver_rejects_existing_key_outside_candidates() -> None:
    """LLM이 후보 목록 밖의 기존 key를 지목하면 안전하게 실패한다."""
    draft = prepare_wiki_identity_resolution(
        classification=WikiClassification(
            entities=[EntityClassification(name="머신러닝")]
        ),
        existing_entities=[],
        existing_concepts=[_entry("concept", "머신-러닝", "머신 러닝")],
    )

    with pytest.raises(ValueError, match="후보에 없는"):
        resolve_wiki_identity_conflicts(
            draft=draft,
            source_title="머신러닝",
            model="test-model",
            completion=lambda *args, **kwargs: _completion(
                {
                    "resolutions": [
                        {
                            "conflict_id": draft.conflicts[0].conflict_id,
                            "action": "match_existing",
                            "target_kind": "concept",
                            "target_key": "hallucinated-key",
                        }
                    ]
                }
            ),
        )


def test_resolver_rejects_missing_conflict_decision() -> None:
    """LLM이 후보군 하나라도 누락하면 미해결 상태를 저장하지 않는다."""
    draft = prepare_wiki_identity_resolution(
        classification=WikiClassification(
            entities=[EntityClassification(name="머신러닝")]
        ),
        existing_entities=[],
        existing_concepts=[_entry("concept", "머신-러닝", "머신 러닝")],
    )

    with pytest.raises(ValueError, match="판정이 누락"):
        resolve_wiki_identity_conflicts(
            draft=draft,
            source_title="머신러닝",
            model="test-model",
            completion=lambda *args, **kwargs: _completion({"resolutions": []}),
        )
