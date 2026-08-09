"""별도 Relation Linker의 전체 후보 검토와 품질 게이트를 검증한다."""

import json

from agent.wiki_builder.api import (
    RelationCandidateSignal,
    WikiRelationCandidate,
    build_relation_candidate_sets,
    link_wiki_relations,
)
from shared.wiki_models import (
    ConceptClassification,
    ExistingWikiEntry,
    WikiClassification,
    WikiRelationClassification,
    WikiRelationPlan,
)


def _weather_candidate() -> WikiRelationCandidate:
    """온보딩에서 사용자가 선택한 날씨 Concept 후보를 만든다."""
    return WikiRelationCandidate(
        entry=ExistingWikiEntry(
            document_kind="concept",
            document_key="weather",
            title="날씨",
            domain="term",
            summary="사용자가 온보딩에서 직접 선택한 관심 주제",
            metadata={"aliases": ["기상"]},
        ),
        score=0.78,
        signals=(
            RelationCandidateSignal(
                kind="onboarding_anchor",
                score=1.0,
                contribution=0.25,
                detail="concept:weather",
            ),
        ),
    )


def test_linker_connects_heatwave_to_onboarding_weather_semantically() -> None:
    """원문에 날씨라는 단어가 없어도 온보딩 anchor를 의미 관계로 연결한다."""
    source = "서울은 38도를 넘는 폭염이 이어지고 온열질환 환자가 늘었다."
    classification = WikiClassification(
        concepts=[
            ConceptClassification(
                title="폭염",
                subtype="phenomenon",
                definition="매우 심한 더위 현상",
            )
        ]
    )

    def completion(_system: str, _user: str, *, model: str) -> str:
        """날씨의 하위 주제 판정을 반환하는 가짜 LLM이다."""
        assert model == "test-model"
        return json.dumps(
            {
                "relations": [
                    {
                        "source_ref": "N1",
                        "target_ref": "X1",
                        "relation_type": "subtopic_of",
                        "evidence": source,
                        "provenance_kind": "semantic_inference",
                        "confidence": 0.86,
                        "review_status": "accepted",
                        "rationale": "폭염은 날씨의 세부 현상이다.",
                    }
                ],
                "dispositions": [
                    {
                        "node_ref": "N1",
                        "disposition": "connect",
                        "reason": "날씨와 상·하위 관계",
                    }
                ],
            },
            ensure_ascii=False,
        )

    result = link_wiki_relations(
        source_title="폭염 뉴스",
        source_content=source,
        classification=classification,
        candidates_by_node={"N1": [_weather_candidate()]},
        model="test-model",
        completion=completion,
    )

    assert len(result.relations) == 1
    relation = result.relations[0]
    assert relation.relation_type == "subtopic_of"
    assert relation.target_matched_key == "weather"
    assert relation.provenance_kind == "semantic_inference"
    assert relation.confidence == 0.86
    assert result.node_dispositions[0].disposition == "connect"


def test_linker_always_replaces_partial_extraction_relations_with_full_review() -> None:
    """추출 결과에 Edge가 일부 있어도 Linker 검토를 생략하지 않는다."""
    source = "폭염은 열대야를 일으키고 온열질환에 영향을 준다."
    classification = WikiClassification(
        concepts=[
            ConceptClassification(title="폭염"),
            ConceptClassification(title="열대야"),
            ConceptClassification(title="온열질환"),
        ],
        relations=[
            WikiRelationClassification(
                source_name="폭염",
                source_kind="concept",
                target_name="열대야",
                target_kind="concept",
                relation_type="causes",
                evidence="폭염은 열대야를 일으키고",
            )
        ],
    )
    calls = 0

    def completion(_system: str, _user: str, *, model: str) -> str:
        """완전성 검토로 두 관계를 반환한다."""
        nonlocal calls
        calls += 1
        return json.dumps(
            {
                "relations": [
                    {
                        "source_ref": "N1",
                        "target_ref": "N2",
                        "relation_type": "causes",
                        "evidence": "폭연은 열대야를 일으키고".replace("폭연", "폭염"),
                        "provenance_kind": "source_explicit",
                        "confidence": 0.95,
                        "review_status": "accepted",
                    },
                    {
                        "source_ref": "N1",
                        "target_ref": "N3",
                        "relation_type": "affects",
                        "evidence": "온열질환에 영향을 준다",
                        "provenance_kind": "source_explicit",
                        "confidence": 0.94,
                        "review_status": "accepted",
                    },
                ],
                "dispositions": [],
            },
            ensure_ascii=False,
        )

    result = link_wiki_relations(
        source_title="폭염",
        source_content=source,
        classification=classification,
        candidates_by_node={},
        model="test-model",
        completion=completion,
    )

    assert calls == 1
    assert {relation.relation_type for relation in result.relations} == {
        "causes",
        "affects",
    }
    assert all(item.disposition == "connect" for item in result.node_dispositions)


def test_linker_rejects_low_confidence_comention_and_marks_standalone() -> None:
    """단순 공동 출현 추론은 신뢰도 기준을 넘지 못하면 저장하지 않는다."""
    source = "서울의 축제 소식 뒤에 태풍 돌핀 소식을 전했다."
    classification = WikiClassification(
        concepts=[
            ConceptClassification(title="축제"),
            ConceptClassification(title="태풍 돌핀"),
        ]
    )

    def completion(_system: str, _user: str, *, model: str) -> str:
        """낮은 신뢰도의 단순 공동 출현 Edge를 반환한다."""
        return json.dumps(
            {
                "relations": [
                    {
                        "source_ref": "N1",
                        "target_ref": "N2",
                        "relation_type": "associated_with",
                        "evidence": source,
                        "provenance_kind": "semantic_inference",
                        "confidence": 0.41,
                        "review_status": "accepted",
                        "rationale": "같은 기사에 있음",
                    }
                ],
                "dispositions": [
                    {"node_ref": "N1", "disposition": "connect", "reason": "공동 출현"},
                    {"node_ref": "N2", "disposition": "connect", "reason": "공동 출현"},
                ],
            },
            ensure_ascii=False,
        )

    result = link_wiki_relations(
        source_title="소식",
        source_content=source,
        classification=classification,
        candidates_by_node={},
        model="test-model",
        completion=completion,
    )

    assert result.relations == []
    assert all(item.disposition == "standalone" for item in result.node_dispositions)
    assert any("신뢰도" in warning for warning in result.relation_warnings)


def test_linker_disposition_connection_is_case_insensitive() -> None:
    """영문 노드 표기 대소문자가 달라도 검증된 연결 처리를 유지한다."""
    source = "OpenAI develops GPT models."
    classification = WikiClassification(
        concepts=[
            ConceptClassification(title="OpenAI"),
            ConceptClassification(title="GPT"),
        ]
    )

    def completion(_system: str, _user: str, *, model: str) -> str:
        """노드 이름과 다른 대소문자 표기를 포함한 관계를 반환한다."""
        return json.dumps(
            {
                "relations": [
                    {
                        "source_ref": "N1",
                        "target_ref": "N2",
                        "relation_type": "associated_with",
                        "evidence": source,
                        "provenance_kind": "source_explicit",
                        "confidence": 0.95,
                        "review_status": "accepted",
                    }
                ],
                "dispositions": [],
            }
        )

    result = link_wiki_relations(
        source_title="AI",
        source_content=source,
        classification=classification,
        candidates_by_node={},
        model="test-model",
        completion=completion,
    )

    assert [item.disposition for item in result.node_dispositions] == [
        "connect",
        "connect",
    ]


def test_candidate_sets_do_not_expand_unreviewed_graph_edges() -> None:
    """검토되지 않은 기존 Edge는 관계 후보의 Graph 신호로 재사용하지 않는다."""
    classification = WikiClassification(
        concepts=[
            ConceptClassification(
                title="날씨",
                matched_existing_key="weather",
            )
        ]
    )
    entries = [
        _weather_candidate().entry,
        ExistingWikiEntry(
            document_kind="concept",
            document_key="heatwave",
            title="폭염",
            domain="phenomenon",
            summary=None,
        ),
    ]
    relation = WikiRelationPlan(
        source_document_kind="concept",
        source_document_key="weather",
        target_document_kind="concept",
        target_document_key="heatwave",
        relation_type="subtopic_of",
        metadata={"status": "active", "review_status": "unreviewed"},
    )

    result = build_relation_candidate_sets(
        classification=classification,
        existing_entries=entries,
        existing_relations=[relation],
    )

    assert result["N1"] == []
