"""INT-001 관심 후보 추출 규칙을 검증한다."""

import asyncio

import pytest

from domain.interests.api import int_001


def _node(
    document_id: str,
    title: str,
    *,
    degree: float = 0.0,
    domain: str | None = "product",
    document_kind: str = "entity",
    aliases: list[str] | None = None,
    source_count: int = 1,
    source_types: list[str] | None = None,
    last_activity_at: str | None = "2026-07-20T00:00:00+00:00",
) -> dict[str, object]:
    """검증용 Entity·Concept 노드 Row를 만든다."""
    return {
        "document_id": document_id,
        "document_kind": document_kind,
        "document_key": title.casefold(),
        "title": title,
        "domain": domain,
        "source_metadata": {"aliases": aliases or []},
        "degree": degree,
        "source_count": source_count,
        "source_types": source_types or ["web_clipping"],
        "last_activity_at": last_activity_at,
    }


def test_int_001_ranks_nodes_by_connection_degree() -> None:
    """연결 수가 많은 노드가 더 높은 구조 점수를 갖는지 검증한다."""
    candidates = asyncio.run(
        int_001(
            [
                _node("doc-1", "Obsidian", degree=4.0, aliases=["옵시디언"]),
                _node("doc-2", "Markdown", degree=1.0, document_kind="concept"),
            ],
            limit=10,
        )
    )

    assert [candidate.topic for candidate in candidates] == ["Obsidian", "Markdown"]
    assert candidates[0].score == 1.0
    assert candidates[0].score > candidates[1].score
    assert candidates[0].evidence["degree"] == 4.0
    assert candidates[0].evidence["aliases"] == ["옵시디언"]
    assert candidates[0].document_ids == ("doc-1",)


def test_int_001_keeps_node_titles_without_tokenizing() -> None:
    """노드 제목을 토큰으로 쪼개지 않고 그대로 Topic으로 쓰는지 검증한다."""
    candidates = asyncio.run(
        int_001([_node("doc-1", "검색 증강 생성", degree=2.0)], limit=10)
    )

    assert [candidate.topic for candidate in candidates] == ["검색 증강 생성"]


def test_int_001_carries_scoring_signals_into_evidence() -> None:
    """INT-005가 쓸 최신성·행동 강도 신호를 근거에 담는지 검증한다."""
    candidates = asyncio.run(
        int_001(
            [
                _node(
                    "doc-1",
                    "LangGraph",
                    degree=3.0,
                    source_count=2,
                    source_types=["memo", "web_clipping"],
                    last_activity_at="2026-07-01T00:00:00+00:00",
                )
            ],
            limit=10,
        )
    )

    evidence = candidates[0].evidence
    assert evidence["source_count"] == 2
    assert evidence["source_types"] == ["memo", "web_clipping"]
    assert evidence["last_activity_at"] == "2026-07-01T00:00:00+00:00"
    assert evidence["structure_weight"] > 1.0


def test_int_001_merges_nodes_sharing_a_title() -> None:
    """제목이 같은 노드를 하나의 후보로 합치고 근거를 모으는지 검증한다."""
    candidates = asyncio.run(
        int_001(
            [
                _node("doc-1", "PostgreSQL", degree=1.0, domain=None),
                _node("doc-2", "postgresql", degree=2.0, domain="database"),
            ],
            limit=10,
        )
    )

    assert len(candidates) == 1
    assert candidates[0].document_ids == ("doc-1", "doc-2")
    assert candidates[0].evidence["degree"] == 3.0
    assert candidates[0].category == "database"


def test_int_001_drops_generic_domain_category() -> None:
    """분류에 쓸 수 없는 other 영역은 Category로 남기지 않는지 검증한다."""
    candidates = asyncio.run(
        int_001([_node("doc-1", "Unknown", domain="other")], limit=10)
    )

    assert candidates[0].category is None


def test_int_001_is_deterministic_and_validates_limit() -> None:
    """같은 노드는 같은 후보 순서를 만들고 잘못된 limit을 거절하는지 검증한다."""
    nodes = [_node("doc-1", "PostgreSQL", degree=2.0)]

    assert asyncio.run(int_001(nodes)) == asyncio.run(int_001(nodes))
    with pytest.raises(ValueError, match="limit"):
        asyncio.run(int_001(nodes, limit=0))


def test_int_001_drops_seed_only_node_outside_onboarding_labels() -> None:
    """시드가 유일한 근거인 묶음 노드를 관심 후보에서 빼는지 검증한다."""
    candidates = asyncio.run(
        int_001(
            [
                _node(
                    "doc-1",
                    "온보딩 관심 주제",
                    degree=3.0,
                    document_kind="concept",
                    source_types=["onboarding_seed"],
                ),
                _node(
                    "doc-2",
                    "생성형 AI",
                    degree=1.0,
                    source_types=["onboarding_seed"],
                ),
            ],
            limit=10,
            onboarding_seed_labels=["생성형 AI", "반도체"],
        )
    )

    assert [candidate.topic for candidate in candidates] == ["생성형 AI"]


def test_int_001_keeps_seed_node_matching_label_partially() -> None:
    """Wiki Builder가 라벨을 늘여 쓴 시드 노드는 후보로 남기는지 검증한다."""
    candidates = asyncio.run(
        int_001(
            [_node("doc-1", "기준금리", source_types=["onboarding_seed"])],
            limit=10,
            onboarding_seed_labels=["금리"],
        )
    )

    assert [candidate.topic for candidate in candidates] == ["기준금리"]


def test_int_001_keeps_seed_node_matching_label_by_alias() -> None:
    """제목은 달라도 별칭이 라벨과 맞으면 후보로 남기는지 검증한다."""
    candidates = asyncio.run(
        int_001(
            [
                _node(
                    "doc-1",
                    "Generative AI",
                    aliases=["생성형 AI"],
                    source_types=["onboarding_seed"],
                )
            ],
            limit=10,
            onboarding_seed_labels=["생성형 AI"],
        )
    )

    assert [candidate.topic for candidate in candidates] == ["Generative AI"]


def test_int_001_keeps_seed_node_once_real_sources_arrive() -> None:
    """실제 저장 근거가 쌓인 노드는 라벨과 무관하게 후보로 남기는지 검증한다."""
    candidates = asyncio.run(
        int_001(
            [
                _node(
                    "doc-1",
                    "온보딩 관심 주제",
                    document_kind="concept",
                    source_types=["onboarding_seed", "web_clipping"],
                )
            ],
            limit=10,
            onboarding_seed_labels=["생성형 AI"],
        )
    )

    assert [candidate.topic for candidate in candidates] == ["온보딩 관심 주제"]


def test_int_001_keeps_seed_nodes_when_labels_unknown() -> None:
    """라벨을 알 수 없으면 시드 노드를 임의로 빼지 않는지 검증한다."""
    candidates = asyncio.run(
        int_001(
            [
                _node(
                    "doc-1",
                    "온보딩 관심 주제",
                    document_kind="concept",
                    source_types=["onboarding_seed"],
                )
            ],
            limit=10,
        )
    )

    assert [candidate.topic for candidate in candidates] == ["온보딩 관심 주제"]


def test_int_001_ignores_rows_without_identity() -> None:
    """document_id나 제목이 없는 Row를 후보에서 제외하는지 검증한다."""
    candidates = asyncio.run(
        int_001(
            [
                _node("", "제목만 있는 노드"),
                _node("doc-2", "   "),
                _node("doc-3", "정상 노드"),
            ],
            limit=10,
        )
    )

    assert [candidate.topic for candidate in candidates] == ["정상 노드"]
