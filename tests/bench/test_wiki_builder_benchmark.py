"""Personal Wiki Builder 벤치마크의 관계 채점 기준을 검증한다."""

from bench.wiki_builder.run import _score
from shared.wiki_models import WikiClassification, WikiRelationClassification


def _relation() -> WikiRelationClassification:
    """벤치마크 채점에 사용할 검증된 Entity 관계를 반환한다."""
    return WikiRelationClassification(
        source_name="Sam Altman",
        source_kind="entity",
        target_name="OpenAI",
        target_kind="entity",
        relation_type="entity_relation",
        evidence="Sam Altman은 OpenAI의 CEO다.",
    )


def test_score_requires_expected_wiki_relation() -> None:
    """Dataset에 지정된 관계가 없으면 벤치마크를 실패 처리한다."""
    expected = {
        "relations": [
            {
                "source_kind": "entity",
                "source_name": "Sam Altman",
                "target_kind": "entity",
                "target_name": "OpenAI",
                "relation_type": "entity_relation",
            }
        ]
    }

    passed, errors = _score(WikiClassification(), expected)

    assert passed is False
    assert errors == ["missing relation: Sam Altman -> OpenAI / entity_relation"]


def test_score_accepts_expected_wiki_relation() -> None:
    """출발·도착 노드와 유형이 일치하는 관계를 성공 처리한다."""
    expected = {
        "relations": [
            {
                "source_kind": "entity",
                "source_name": "sam altman",
                "target_kind": "entity",
                "target_name": "openai",
                "relation_type": "entity_relation",
            }
        ]
    }

    passed, errors = _score(
        WikiClassification(relations=[_relation()]),
        expected,
    )

    assert passed is True
    assert errors == []


def test_score_rejects_relation_for_isolated_node_case() -> None:
    """관계가 없어야 하는 경계 케이스의 허위 Edge를 실패 처리한다."""
    passed, errors = _score(
        WikiClassification(relations=[_relation()]),
        {"max_relations": 0},
    )

    assert passed is False
    assert errors == ["too many relations: 1"]
