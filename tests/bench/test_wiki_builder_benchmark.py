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


def _expected_relation(**overrides: str) -> dict[str, str]:
    """Dataset의 관계 기대값 한 건을 만든다."""
    relation = {
        "source_kind": "entity",
        "source_name": "Sam Altman",
        "target_kind": "entity",
        "target_name": "OpenAI",
        "relation_type": "entity_relation",
    }
    relation.update(overrides)
    return relation


def test_score_requires_expected_wiki_relation() -> None:
    """Dataset에 지정된 관계가 없으면 벤치마크를 실패 처리한다."""
    expected = {"relations": [_expected_relation()]}

    passed, errors, stats = _score(WikiClassification(), expected)

    assert passed is False
    assert errors == ["missing relation: Sam Altman -> OpenAI / entity_relation"]
    assert (stats["tp"], stats["fn"]) == (0, 1)


def test_score_accepts_expected_wiki_relation() -> None:
    """출발·도착 노드와 유형이 일치하는 관계를 성공 처리한다."""
    expected = {
        "relations": [
            _expected_relation(source_name="sam altman", target_name="openai")
        ]
    }

    passed, errors, stats = _score(
        WikiClassification(relations=[_relation()]),
        expected,
    )

    assert passed is True
    assert errors == []
    assert (stats["tp"], stats["fn"]) == (1, 0)


def test_score_rejects_relation_for_isolated_node_case() -> None:
    """관계가 없어야 하는 경계 케이스의 허위 Edge를 실패 처리한다."""
    passed, errors, _ = _score(
        WikiClassification(relations=[_relation()]),
        {"max_relations": 0},
    )

    assert passed is False
    assert errors == ["too many relations: 1"]


def test_score_flags_forbidden_relation() -> None:
    """연결되면 안 되는 쌍을 만들면 금지 위반으로 집계한다."""
    expected = {"forbidden_relations": [_expected_relation()]}

    passed, errors, stats = _score(
        WikiClassification(relations=[_relation()]),
        expected,
    )

    assert passed is False
    assert errors == ["forbidden relation: Sam Altman -> OpenAI"]
    assert stats["forbidden_hit"] == 1


def test_score_flags_forbidden_relation_in_reverse_direction() -> None:
    """금지 쌍은 방향을 뒤집어 연결해도 위반으로 본다."""
    expected = {
        "forbidden_relations": [
            _expected_relation(source_name="OpenAI", target_name="Sam Altman")
        ]
    }

    passed, _errors, stats = _score(
        WikiClassification(relations=[_relation()]),
        expected,
    )

    assert passed is False
    assert stats["forbidden_hit"] == 1


def test_score_counts_reversed_expected_relation_as_missing() -> None:
    """정답과 방향이 반대인 관계는 누락으로 세되 역방향 일치로 표시한다."""
    expected = {
        "relations": [
            _expected_relation(source_name="OpenAI", target_name="Sam Altman")
        ]
    }

    passed, _errors, stats = _score(
        WikiClassification(relations=[_relation()]),
        expected,
    )

    assert passed is False
    assert (stats["fn"], stats["reversed_only"]) == (1, 1)
