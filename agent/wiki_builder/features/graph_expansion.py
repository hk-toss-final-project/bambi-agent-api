"""검증된 개인 Wiki Graph의 제한적 검색 확장을 계산한다.

관계 수명주기·검토 상태·근거·신뢰도를 품질 Gate에서 먼저 검사하고,
성숙한 Graph에만 2-hop personalized PageRank를 적용한다. Gate를 통과하지
못하면 검증된 직접 이웃만 반환하거나 명시적으로 빈 결과를 반환한다.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from agent.wiki_builder.features.relation_candidates import WikiNodeIdentity


GRAPH_EXPANSION_RELATION_TYPES = frozenset(
    {
        # 기존 Graph와의 하위 호환 관계 유형
        "entity_relation",
        "applies_concept",
        "related_concept",
        # 의미를 명시하는 신규 관계 유형 8종
        "instance_of",
        "subtopic_of",
        "part_of",
        "located_in",
        "occurs_in",
        "affects",
        "causes",
        "associated_with",
    }
)

_PROVENANCE_FACTORS: Mapping[str, float] = {
    "source_explicit": 1.0,
    "semantic_inference": 0.85,
    "user_declared": 1.0,
    "system_rule": 0.95,
}


@dataclass(frozen=True, slots=True)
class WikiGraphExpansionEdge:
    """검색 확장 품질 Gate와 점수 계산에 사용할 관계 Head."""

    source: WikiNodeIdentity
    target: WikiNodeIdentity
    relation_type: str
    status: str = "active"
    review_status: str = "accepted"
    provenance_kind: str = "source_explicit"
    confidence: float = 1.0
    weight: float = 1.0
    supported: bool = True


@dataclass(frozen=True, slots=True)
class GraphMaturityPolicy:
    """2-hop Graph 확장을 허용할 품질·크기 임계값."""

    minimum_verified_edges: int = 3
    minimum_verified_edge_ratio: float = 0.75
    maximum_hub_dominance: float = 0.80
    source_explicit_min_confidence: float = 0.70
    semantic_inference_min_confidence: float = 0.78
    user_declared_min_confidence: float = 0.90
    system_rule_min_confidence: float = 0.90
    maximum_hops: int = 2
    damping: float = 0.75
    iterations: int = 24


@dataclass(frozen=True, slots=True)
class GraphMaturityReport:
    """Graph 품질 Gate 판정과 그 근거가 되는 집계 지표."""

    passed: bool
    active_edge_count: int
    verified_edge_count: int
    excluded_edge_count: int
    superseded_edge_count: int
    verified_edge_ratio: float
    hub_dominance: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GraphExpansionScore:
    """확장 후보 노드의 개인화 Graph 점수와 Seed로부터의 거리."""

    node: WikiNodeIdentity
    score: float
    hops: int


@dataclass(frozen=True, slots=True)
class GraphExpansionResult:
    """품질 Gate와 폴백 방식을 포함한 Graph 확장 결과."""

    gate_passed: bool
    mode: Literal["bounded_ppr", "one_hop", "empty"]
    scores: tuple[GraphExpansionScore, ...]
    maturity: GraphMaturityReport


def _validate_policy(policy: GraphMaturityPolicy) -> None:
    """Graph 품질·PageRank 설정값이 안전한 범위인지 검사한다."""
    if policy.minimum_verified_edges < 1:
        raise ValueError("minimum_verified_edges는 1 이상이어야 합니다.")
    for name, value in (
        ("minimum_verified_edge_ratio", policy.minimum_verified_edge_ratio),
        ("maximum_hub_dominance", policy.maximum_hub_dominance),
        ("source_explicit_min_confidence", policy.source_explicit_min_confidence),
        ("semantic_inference_min_confidence", policy.semantic_inference_min_confidence),
        ("user_declared_min_confidence", policy.user_declared_min_confidence),
        ("system_rule_min_confidence", policy.system_rule_min_confidence),
        ("damping", policy.damping),
    ):
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"{name}은 0과 1 사이여야 합니다.")
    if policy.maximum_hops != 2:
        raise ValueError("Graph 확장 깊이는 현재 2-hop으로 제한됩니다.")
    if policy.iterations < 1:
        raise ValueError("iterations는 1 이상이어야 합니다.")


def _minimum_confidence(edge: WikiGraphExpansionEdge, policy: GraphMaturityPolicy) -> float:
    """관계 provenance에 해당하는 최소 신뢰도 임계값을 반환한다."""
    return {
        "source_explicit": policy.source_explicit_min_confidence,
        "semantic_inference": policy.semantic_inference_min_confidence,
        "user_declared": policy.user_declared_min_confidence,
        "system_rule": policy.system_rule_min_confidence,
    }.get(edge.provenance_kind, math.inf)


def _is_verified(edge: WikiGraphExpansionEdge, policy: GraphMaturityPolicy) -> bool:
    """관계가 검색 확장에 쓸 수 있는 활성·검증 Edge인지 판정한다."""
    return (
        edge.status == "active"
        and edge.review_status == "accepted"
        and edge.relation_type in GRAPH_EXPANSION_RELATION_TYPES
        and edge.provenance_kind in _PROVENANCE_FACTORS
        and edge.supported
        and edge.source != edge.target
        and math.isfinite(edge.confidence)
        and edge.confidence >= _minimum_confidence(edge, policy)
        and edge.confidence <= 1.0
        and math.isfinite(edge.weight)
        and edge.weight > 0.0
    )


def _edge_signature(
    edge: WikiGraphExpansionEdge,
) -> tuple[WikiNodeIdentity, WikiNodeIdentity, str]:
    """같은 방향·관계 유형의 중복 Head를 식별하는 서명을 만든다."""
    return edge.source, edge.target, edge.relation_type


def _effective_weight(edge: WikiGraphExpansionEdge) -> float:
    """저장 가중치에 신뢰도와 provenance 신뢰 계수를 반영한다."""
    return (
        edge.weight
        * edge.confidence
        * _PROVENANCE_FACTORS[edge.provenance_kind]
    )


def _verified_edges(
    edges: Sequence[WikiGraphExpansionEdge],
    policy: GraphMaturityPolicy,
) -> tuple[WikiGraphExpansionEdge, ...]:
    """중복 관계 중 가장 강한 검증 Edge만 안정적으로 선택한다."""
    selected: dict[
        tuple[WikiNodeIdentity, WikiNodeIdentity, str], WikiGraphExpansionEdge
    ] = {}
    for edge in edges:
        if not _is_verified(edge, policy):
            continue
        signature = _edge_signature(edge)
        current = selected.get(signature)
        if current is None or _effective_weight(edge) > _effective_weight(current):
            selected[signature] = edge
    return tuple(
        selected[signature]
        for signature in sorted(
            selected,
            key=lambda item: (
                item[0].document_kind,
                item[0].document_key,
                item[1].document_kind,
                item[1].document_key,
                item[2],
            ),
        )
    )


def _hub_dominance(edges: Sequence[WikiGraphExpansionEdge]) -> float:
    """검증 Edge 중 가장 많은 Edge가 닿는 단일 Hub의 비율을 계산한다."""
    if not edges:
        return 0.0
    incident_edges: dict[WikiNodeIdentity, set[int]] = defaultdict(set)
    for index, edge in enumerate(edges):
        incident_edges[edge.source].add(index)
        incident_edges[edge.target].add(index)
    maximum_incident = max((len(items) for items in incident_edges.values()), default=0)
    return maximum_incident / len(edges)


def evaluate_graph_maturity(
    edges: Sequence[WikiGraphExpansionEdge],
    *,
    policy: GraphMaturityPolicy = GraphMaturityPolicy(),
) -> GraphMaturityReport:
    """관계 Snapshot이 2-hop 확장에 충분히 검증되고 분산됐는지 평가한다."""
    _validate_policy(policy)
    active_edges = tuple(edge for edge in edges if edge.status == "active")
    superseded_count = sum(edge.status == "superseded" for edge in edges)
    verified = _verified_edges(active_edges, policy)
    ratio = len(verified) / len(active_edges) if active_edges else 0.0
    dominance = _hub_dominance(verified)
    reasons: list[str] = []
    if len(verified) < policy.minimum_verified_edges:
        reasons.append(
            f"검증 Edge {len(verified)}개가 최소 {policy.minimum_verified_edges}개보다 적습니다."
        )
    if ratio < policy.minimum_verified_edge_ratio:
        reasons.append(
            f"검증 Edge 비율 {ratio:.3f}이 최소 {policy.minimum_verified_edge_ratio:.3f}보다 낮습니다."
        )
    if dominance > policy.maximum_hub_dominance:
        reasons.append(
            f"Hub 편중 {dominance:.3f}이 최대 {policy.maximum_hub_dominance:.3f}보다 높습니다."
        )
    return GraphMaturityReport(
        passed=not reasons,
        active_edge_count=len(active_edges),
        verified_edge_count=len(verified),
        excluded_edge_count=len(active_edges) - len(verified),
        superseded_edge_count=superseded_count,
        verified_edge_ratio=ratio,
        hub_dominance=dominance,
        reasons=tuple(reasons),
    )


def _adjacency(
    edges: Iterable[WikiGraphExpansionEdge],
) -> dict[WikiNodeIdentity, dict[WikiNodeIdentity, float]]:
    """검증된 방향 관계를 양방향 검색용 가중 인접 Map으로 바꾼다."""
    result: dict[WikiNodeIdentity, dict[WikiNodeIdentity, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    for edge in edges:
        weight = _effective_weight(edge)
        result[edge.source][edge.target] += weight
        result[edge.target][edge.source] += weight
    return {node: dict(neighbors) for node, neighbors in result.items()}


def _bounded_distances(
    seed: WikiNodeIdentity,
    adjacency: Mapping[WikiNodeIdentity, Mapping[WikiNodeIdentity, float]],
    *,
    maximum_hops: int,
) -> dict[WikiNodeIdentity, int]:
    """Seed에서 지정한 hop 이내에 도달하는 노드의 최단 거리를 계산한다."""
    distances = {seed: 0}
    queue: deque[WikiNodeIdentity] = deque((seed,))
    while queue:
        current = queue.popleft()
        if distances[current] >= maximum_hops:
            continue
        for neighbor in adjacency.get(current, {}):
            if neighbor in distances:
                continue
            distances[neighbor] = distances[current] + 1
            queue.append(neighbor)
    return distances


def _personalized_scores(
    seed: WikiNodeIdentity,
    adjacency: Mapping[WikiNodeIdentity, Mapping[WikiNodeIdentity, float]],
    distances: Mapping[WikiNodeIdentity, int],
    *,
    damping: float,
    iterations: int,
) -> dict[WikiNodeIdentity, float]:
    """2-hop 부분 Graph에서 Seed 재시작 random-walk 점수를 계산한다."""
    allowed_nodes = set(distances)
    scores = {node: 0.0 for node in allowed_nodes}
    scores[seed] = 1.0
    for _iteration in range(iterations):
        next_scores = {node: 0.0 for node in allowed_nodes}
        next_scores[seed] = 1.0 - damping
        for source, source_score in scores.items():
            neighbors = {
                target: weight
                for target, weight in adjacency.get(source, {}).items()
                if target in allowed_nodes and weight > 0.0
            }
            total_weight = sum(neighbors.values())
            if total_weight <= 0.0:
                next_scores[seed] += damping * source_score
                continue
            for target, weight in neighbors.items():
                next_scores[target] += damping * source_score * weight / total_weight
        scores = next_scores
    return scores


def _ranked_scores(
    scores: Mapping[WikiNodeIdentity, float],
    distances: Mapping[WikiNodeIdentity, int],
    *,
    seed: WikiNodeIdentity,
    top_k: int,
) -> tuple[GraphExpansionScore, ...]:
    """Seed를 제외한 양수 점수 후보를 안정적인 순서와 상한으로 반환한다."""
    if top_k <= 0:
        return ()
    candidates = [
        GraphExpansionScore(node=node, score=score, hops=distances[node])
        for node, score in scores.items()
        if node != seed and score > 0.0
    ]
    candidates.sort(
        key=lambda item: (
            -item.score,
            item.hops,
            item.node.document_kind,
            item.node.document_key,
        )
    )
    return tuple(candidates[:top_k])


def _one_hop_fallback(
    seed: WikiNodeIdentity,
    adjacency: Mapping[WikiNodeIdentity, Mapping[WikiNodeIdentity, float]],
    *,
    top_k: int,
) -> tuple[GraphExpansionScore, ...]:
    """품질 Gate 실패 시 검증된 직접 이웃만 가중치 순으로 반환한다."""
    if top_k <= 0:
        return ()
    neighbors = adjacency.get(seed, {})
    total_weight = sum(weight for weight in neighbors.values() if weight > 0.0)
    if total_weight <= 0.0:
        return ()
    scores = [
        GraphExpansionScore(node=node, score=weight / total_weight, hops=1)
        for node, weight in neighbors.items()
        if weight > 0.0
    ]
    scores.sort(
        key=lambda item: (
            -item.score,
            item.node.document_kind,
            item.node.document_key,
        )
    )
    return tuple(scores[:top_k])


def expand_wiki_graph(
    seed: WikiNodeIdentity,
    edges: Sequence[WikiGraphExpansionEdge],
    *,
    top_k: int = 3,
    fallback: Literal["one_hop", "empty"] = "one_hop",
    policy: GraphMaturityPolicy = GraphMaturityPolicy(),
) -> GraphExpansionResult:
    """품질 Gate 통과 시에만 2-hop 개인화 Graph 확장 후보를 반환한다."""
    if fallback not in {"one_hop", "empty"}:
        raise ValueError("fallback은 one_hop 또는 empty여야 합니다.")
    maturity = evaluate_graph_maturity(edges, policy=policy)
    verified = _verified_edges(edges, policy)
    adjacency = _adjacency(verified)
    if not maturity.passed:
        fallback_scores = (
            _one_hop_fallback(seed, adjacency, top_k=top_k)
            if fallback == "one_hop"
            else ()
        )
        return GraphExpansionResult(
            gate_passed=False,
            mode="one_hop" if fallback_scores else "empty",
            scores=fallback_scores,
            maturity=maturity,
        )
    distances = _bounded_distances(
        seed,
        adjacency,
        maximum_hops=policy.maximum_hops,
    )
    scores = _personalized_scores(
        seed,
        adjacency,
        distances,
        damping=policy.damping,
        iterations=policy.iterations,
    )
    return GraphExpansionResult(
        gate_passed=True,
        mode="bounded_ppr",
        scores=_ranked_scores(
            scores,
            distances,
            seed=seed,
            top_k=top_k,
        ),
        maturity=maturity,
    )
