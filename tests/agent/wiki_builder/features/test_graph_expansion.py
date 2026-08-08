"""개인 Wiki Graph 확장의 품질 Gate와 제한적 random-walk를 검증한다."""

import pytest

from agent.wiki_builder.api import (
    GRAPH_EXPANSION_RELATION_TYPES,
    GraphMaturityPolicy,
    WikiGraphExpansionEdge,
    WikiNodeIdentity,
    evaluate_graph_maturity,
    expand_wiki_graph,
)


def _node(key: str, kind: str = "concept") -> WikiNodeIdentity:
    """테스트용 Wiki 노드 식별자를 만든다."""
    return WikiNodeIdentity(kind, key)


def _edge(
    source: str,
    target: str,
    relation_type: str = "associated_with",
    **overrides: object,
) -> WikiGraphExpansionEdge:
    """기본적으로 검증된 활성 Wiki 관계를 만든다."""
    values: dict[str, object] = {
        "source": _node(source),
        "target": _node(target),
        "relation_type": relation_type,
    }
    values.update(overrides)
    return WikiGraphExpansionEdge(**values)  # type: ignore[arg-type]


def test_graph_expansion_ontology_contains_legacy_and_eight_semantic_types() -> None:
    """검색 확장이 기존 3종과 의미 관계 신규 8종만 허용한다."""
    assert GRAPH_EXPANSION_RELATION_TYPES == {
        "entity_relation",
        "applies_concept",
        "related_concept",
        "instance_of",
        "subtopic_of",
        "part_of",
        "located_in",
        "occurs_in",
        "affects",
        "causes",
        "associated_with",
    }


def test_maturity_excludes_superseded_and_penalizes_unsupported_active_edges() -> None:
    """폐기 Edge는 모수에서도 빼고 근거 없는 활성 Edge는 검증 비율을 낮춘다."""
    edges = [
        _edge("weather", "heatwave", "subtopic_of"),
        _edge("heatwave", "typhoon", "associated_with"),
        _edge("typhoon", "weather", "associated_with"),
        _edge("weather", "finance", supported=False),
        _edge("weather", "old-topic", status="superseded"),
    ]

    report = evaluate_graph_maturity(edges)

    assert report.passed is True
    assert report.active_edge_count == 4
    assert report.verified_edge_count == 3
    assert report.excluded_edge_count == 1
    assert report.superseded_edge_count == 1
    assert report.verified_edge_ratio == pytest.approx(0.75)
    assert report.hub_dominance == pytest.approx(2 / 3)


def test_mature_graph_returns_only_nodes_within_two_hops_using_ppr() -> None:
    """성숙한 Graph는 Seed 기준 2-hop 부분 Graph에서만 개인화 점수를 계산한다."""
    weather = _node("weather")
    edges = [
        _edge("weather", "heatwave", "subtopic_of", weight=1.0),
        _edge("heatwave", "heat-illness", "affects", weight=0.9),
        _edge("weather", "typhoon", "subtopic_of", weight=0.8),
        _edge("typhoon", "storm-surge", "causes", weight=0.7),
        _edge("heatwave", "typhoon", "associated_with", weight=0.6),
        _edge("storm-surge", "coast", "occurs_in", weight=0.6),
    ]

    result = expand_wiki_graph(weather, edges, top_k=10)

    assert result.gate_passed is True
    assert result.mode == "bounded_ppr"
    assert {item.node.document_key for item in result.scores} == {
        "heatwave",
        "heat-illness",
        "typhoon",
        "storm-surge",
    }
    assert all(1 <= item.hops <= 2 for item in result.scores)
    assert "coast" not in {item.node.document_key for item in result.scores}
    assert all(item.node != weather for item in result.scores)


def test_low_verified_ratio_falls_back_to_verified_one_hop_only() -> None:
    """검증 Edge 비율이 낮으면 근거가 있는 직접 이웃만 폴백으로 반환한다."""
    weather = _node("weather")
    edges = [
        _edge("weather", "heatwave", "subtopic_of", weight=0.8),
        _edge("weather", "finance", supported=False, weight=10.0),
        _edge(
            "weather",
            "festival",
            review_status="unreviewed",
            weight=10.0,
        ),
    ]

    result = expand_wiki_graph(
        weather,
        edges,
        top_k=3,
        policy=GraphMaturityPolicy(minimum_verified_edges=1),
    )

    assert result.gate_passed is False
    assert result.mode == "one_hop"
    assert [item.node.document_key for item in result.scores] == ["heatwave"]
    assert result.scores[0].hops == 1
    assert any("검증 Edge 비율" in reason for reason in result.maturity.reasons)


def test_hub_dominance_blocks_two_hop_expansion() -> None:
    """관계가 단일 Hub에 과도하게 몰리면 2-hop 확장을 열지 않는다."""
    hub = _node("seoul")
    edges = [
        _edge("seoul", "weather", weight=1.0),
        _edge("seoul", "festival", weight=0.8),
        _edge("seoul", "finance", weight=0.6),
        _edge("seoul", "transport", weight=0.4),
    ]

    result = expand_wiki_graph(hub, edges, top_k=2)

    assert result.gate_passed is False
    assert result.mode == "one_hop"
    assert result.maturity.hub_dominance == 1.0
    assert [item.node.document_key for item in result.scores] == [
        "weather",
        "festival",
    ]
    assert any("Hub 편중" in reason for reason in result.maturity.reasons)


def test_explicit_empty_fallback_never_returns_failed_graph_neighbors() -> None:
    """호출자가 빈 폴백을 고르면 Gate 실패 Graph의 이웃을 반환하지 않는다."""
    result = expand_wiki_graph(
        _node("weather"),
        [_edge("weather", "heatwave")],
        fallback="empty",
    )

    assert result.gate_passed is False
    assert result.mode == "empty"
    assert result.scores == ()


def test_low_confidence_or_unknown_relation_is_never_traversed() -> None:
    """provenance 임계값 미달과 Ontology 밖 관계는 확장 경로에서 제외한다."""
    policy = GraphMaturityPolicy(minimum_verified_edges=1)
    result = expand_wiki_graph(
        _node("weather"),
        [
            _edge(
                "weather",
                "heatwave",
                provenance_kind="semantic_inference",
                confidence=0.77,
            ),
            _edge("weather", "finance", relation_type="co_mentioned"),
        ],
        policy=policy,
    )

    assert result.mode == "empty"
    assert result.scores == ()
    assert result.maturity.verified_edge_count == 0


def test_graph_expansion_validates_policy_and_fallback() -> None:
    """잘못된 임계값·확장 깊이·폴백 값은 조용히 보정하지 않는다."""
    with pytest.raises(ValueError, match="0과 1 사이"):
        evaluate_graph_maturity(
            [],
            policy=GraphMaturityPolicy(minimum_verified_edge_ratio=1.1),
        )
    with pytest.raises(ValueError, match="2-hop"):
        evaluate_graph_maturity([], policy=GraphMaturityPolicy(maximum_hops=3))
    with pytest.raises(ValueError, match="fallback"):
        expand_wiki_graph(_node("weather"), [], fallback="nearest")  # type: ignore[arg-type]
