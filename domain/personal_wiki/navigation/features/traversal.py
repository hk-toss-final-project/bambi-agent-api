"""Navigator 검증 관계의 제한적 Link Traverse 기능."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from psycopg import AsyncConnection

from infrastructure.persistence.api import (
    load_wiki_navigation_relations,
    set_personal_wiki_scope,
)
from shared.wiki_navigation_models import (
    WikiNavigationRelation,
    WikiNavigationRelationSupport,
    WikiNavigationTraversal,
)

type DictRow = dict[str, Any]

_ALLOWED_RELATION_TYPES = frozenset(
    {
        "entity_relation",
        "applies_concept",
        "related_concept",
        "alias_of",
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
_MIN_CONFIDENCE = {
    "source_explicit": 0.70,
    "semantic_inference": 0.78,
    "user_declared": 0.90,
    "system_rule": 0.90,
}


def _verified_relation(row: Mapping[str, object]) -> bool:
    """관계가 Navigator Traverse 품질 Gate를 통과하는지 판정한다."""
    provenance = str(row.get("provenance_kind") or "")
    confidence = float(row.get("confidence") or 0.0)
    supports = row.get("supports")
    return (
        str(row.get("relation_type") or "") in _ALLOWED_RELATION_TYPES
        and str(row.get("review_status") or "") != "rejected"
        and provenance in _MIN_CONFIDENCE
        and math.isfinite(confidence)
        and _MIN_CONFIDENCE[provenance] <= confidence <= 1.0
        and isinstance(supports, Sequence)
        and bool(supports)
    )


def _supports(row: Mapping[str, object]) -> tuple[WikiNavigationRelationSupport, ...]:
    """관계 Row의 active support JSON을 공개 모델로 변환한다."""
    result: list[WikiNavigationRelationSupport] = []
    for raw in row.get("supports") or ():
        if not isinstance(raw, Mapping):
            continue
        result.append(
            WikiNavigationRelationSupport(
                source_document_version_id=str(
                    raw.get("source_document_version_id") or ""
                ),
                provenance_kind=str(raw.get("provenance_kind") or ""),
                confidence=float(raw.get("confidence") or 0.0),
                review_status=str(raw.get("review_status") or ""),
                evidence=str(raw.get("evidence") or ""),
                rationale=str(raw.get("rationale") or ""),
            )
        )
    return tuple(result)


def _peer_and_direction(
    row: Mapping[str, object], frontier: set[str]
) -> tuple[str, str, str] | None:
    """현재 Frontier 기준 상대 Page·원래 방향·출발 Page를 반환한다."""
    source = str(row["source_document_id"])
    target = str(row["target_document_id"])
    if source in frontier:
        return target, "outgoing", source
    if target in frontier:
        return source, "incoming", target
    return None


def _relation_model(
    row: Mapping[str, object], *, direction: str, depth: int
) -> WikiNavigationRelation:
    """검증된 저장소 Row를 공개 Navigator 관계 모델로 변환한다."""
    return WikiNavigationRelation(
        relation_id=str(row["relation_id"]),
        source_document_id=str(row["source_document_id"]),
        target_document_id=str(row["target_document_id"]),
        relation_type=str(row["relation_type"]),
        confidence=float(row["confidence"]),
        provenance_kind=str(row["provenance_kind"]),
        review_status=str(row["review_status"]),
        rationale=str(row.get("rationale") or ""),
        traversal_direction=direction,
        hops=depth,
        supports=_supports(row),
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wnav_003(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    seed_document_ids: Sequence[str],
    max_depth: int = 1,
    max_pages: int = 6,
    seed_page_limit: int | None = None,
    hop_page_limits: Sequence[int] | None = None,
) -> WikiNavigationTraversal:
    """[WNAV-003] 선택 Seed에서 신뢰도 우선·깊이별 예산으로 순회한다."""
    if not user_id.strip():
        raise ValueError("WNAV-003에 user_id가 필요합니다.")
    if not 1 <= max_depth <= 2:
        raise ValueError("WNAV-003 탐색 깊이는 1 또는 2여야 합니다.")
    if not 1 <= max_pages <= 12:
        raise ValueError("WNAV-003 Page 수는 1에서 12 사이여야 합니다.")
    resolved_seed_limit = seed_page_limit if seed_page_limit is not None else max_pages
    if not 1 <= resolved_seed_limit <= max_pages:
        raise ValueError("WNAV-003 Seed Page 수는 전체 Page 상한 안이어야 합니다.")
    resolved_hop_limits = (
        tuple(int(limit) for limit in hop_page_limits)
        if hop_page_limits is not None
        else tuple(max_pages for _ in range(max_depth))
    )
    if len(resolved_hop_limits) != max_depth or any(
        limit < 0 for limit in resolved_hop_limits
    ):
        raise ValueError("WNAV-003 깊이별 Page 할당이 탐색 깊이와 맞지 않습니다.")
    ordered_seeds = list(dict.fromkeys(str(item) for item in seed_document_ids if item))
    if not ordered_seeds:
        return WikiNavigationTraversal((), ())
    visited = ordered_seeds[:resolved_seed_limit]
    visited_set = set(visited)
    frontier = set(visited)
    document_hops = {document_id: 0 for document_id in visited}
    path_scores = {document_id: 1.0 for document_id in visited}
    relations: list[WikiNavigationRelation] = []
    seen_relations: set[str] = set()
    truncated = len(ordered_seeds) > resolved_seed_limit
    carry = max(0, resolved_seed_limit - len(visited))
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        for depth in range(1, max_depth + 1):
            if not frontier:
                break
            rows = await load_wiki_navigation_relations(
                connection,
                user_id=user_id,
                document_ids=sorted(frontier),
            )
            verified_rows: list[tuple[Mapping[str, object], str, str, str, float]] = []
            best_by_peer: dict[
                str, tuple[Mapping[str, object], str, str, str, float]
            ] = {}
            for row in rows:
                relation_id = str(row["relation_id"])
                if relation_id in seen_relations or not _verified_relation(row):
                    continue
                peer_and_direction = _peer_and_direction(row, frontier)
                if peer_and_direction is None:
                    continue
                peer, direction, anchor = peer_and_direction
                path_score = path_scores.get(anchor, 1.0) * float(row["confidence"])
                entry = (row, peer, direction, anchor, path_score)
                verified_rows.append(entry)
                if peer not in visited_set:
                    existing = best_by_peer.get(peer)
                    rank = (-path_score, peer, relation_id, anchor)
                    if existing is None or rank < (
                        -existing[4],
                        existing[1],
                        str(existing[0]["relation_id"]),
                        existing[3],
                    ):
                        best_by_peer[peer] = entry
            allowance = min(
                max_pages - len(visited),
                resolved_hop_limits[depth - 1] + carry,
            )
            ordered_candidates = sorted(
                best_by_peer.values(),
                key=lambda item: (
                    -item[4],
                    item[1],
                    str(item[0]["relation_id"]),
                    item[3],
                ),
            )
            accepted = ordered_candidates[: max(0, allowance)]
            if len(ordered_candidates) > len(accepted):
                truncated = True
            next_frontier = {entry[1] for entry in accepted}
            for row, peer, _direction, _anchor, path_score in accepted:
                visited.append(peer)
                visited_set.add(peer)
                document_hops[peer] = depth
                path_scores[peer] = path_score
            carry = max(
                0,
                resolved_hop_limits[depth - 1] + carry - len(accepted),
            )
            for row, _peer, direction, _anchor, _path_score in verified_rows:
                relation_id = str(row["relation_id"])
                if relation_id in seen_relations:
                    continue
                if not {
                    str(row["source_document_id"]),
                    str(row["target_document_id"]),
                }.issubset(visited_set):
                    continue
                seen_relations.add(relation_id)
                relations.append(
                    _relation_model(row, direction=direction, depth=depth)
                )
            frontier = next_frontier
    return WikiNavigationTraversal(
        document_ids=tuple(visited),
        relations=tuple(relations),
        truncated=truncated,
        document_hops=tuple((item, document_hops[item]) for item in visited),
    )
