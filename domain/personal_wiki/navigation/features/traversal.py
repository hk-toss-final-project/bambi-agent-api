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
) -> tuple[str, str] | None:
    """현재 Frontier 기준 상대 Page와 원래 관계 방향을 반환한다."""
    source = str(row["source_document_id"])
    target = str(row["target_document_id"])
    if source in frontier:
        return target, "outgoing"
    if target in frontier:
        return source, "incoming"
    return None


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wnav_003(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    seed_document_ids: Sequence[str],
    max_depth: int = 1,
    max_pages: int = 6,
) -> WikiNavigationTraversal:
    """[WNAV-003] 선택 Seed에서 검증된 관계를 제한적으로 순회한다."""
    if not user_id.strip():
        raise ValueError("WNAV-003에 user_id가 필요합니다.")
    if not 1 <= max_depth <= 2:
        raise ValueError("WNAV-003 탐색 깊이는 1 또는 2여야 합니다.")
    if not 1 <= max_pages <= 12:
        raise ValueError("WNAV-003 Page 수는 1에서 12 사이여야 합니다.")
    ordered_seeds = list(dict.fromkeys(str(item) for item in seed_document_ids if item))
    if not ordered_seeds:
        return WikiNavigationTraversal((), ())
    visited = ordered_seeds[:max_pages]
    visited_set = set(visited)
    frontier = set(visited)
    relations: list[WikiNavigationRelation] = []
    seen_relations: set[str] = set()
    truncated = len(ordered_seeds) > max_pages
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
            next_frontier: set[str] = set()
            for row in rows:
                relation_id = str(row["relation_id"])
                if relation_id in seen_relations or not _verified_relation(row):
                    continue
                peer_and_direction = _peer_and_direction(row, frontier)
                if peer_and_direction is None:
                    continue
                peer, direction = peer_and_direction
                if peer not in visited_set:
                    if len(visited) >= max_pages:
                        truncated = True
                        continue
                    visited.append(peer)
                    visited_set.add(peer)
                    next_frontier.add(peer)
                seen_relations.add(relation_id)
                relations.append(
                    WikiNavigationRelation(
                        relation_id=relation_id,
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
                )
            frontier = next_frontier
    return WikiNavigationTraversal(
        document_ids=tuple(visited),
        relations=tuple(relations),
        truncated=truncated,
    )
