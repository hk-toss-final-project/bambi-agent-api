"""PostgreSQL Wiki Graph 조회 Row의 응답 조립을 검증한다."""

from datetime import UTC, datetime

from app.schemas.wiki import WikiGraphResponse
from infrastructure.persistence.postgres_wiki_graph import (
    build_wiki_graph_payload,
)


def _node(node_id: str, kind: str, title: str) -> dict[str, object]:
    """Graph Payload 조립 테스트용 Wiki 문서 Row를 만든다."""
    return {
        "id": node_id,
        "document_kind": kind,
        "document_key": title.lower(),
        "file_path": f"{kind}s/{title.lower()}.md",
        "subtype": "product" if kind == "entity" else "method",
        "version": 2,
        "updated_at": datetime(2026, 7, 15, tzinfo=UTC),
        "title": title,
        "summary": f"{title} summary",
        "normalized_content": f"# {title}",
        "source_metadata": {"aliases": [f"{title} alias"]},
    }


def test_build_wiki_graph_payload_counts_edges_and_orphans() -> None:
    """Node 차수와 Entity·Concept·고립 Node 집계를 정확히 계산한다."""
    payload = build_wiki_graph_payload(
        user_id="user-1",
        node_rows=[
            _node("entity-1", "entity", "Obsidian"),
            _node("concept-1", "concept", "Linked Notes"),
            _node("concept-2", "concept", "Orphan"),
        ],
        edge_rows=[
            {
                "source_document_id": "entity-1",
                "target_document_id": "concept-1",
                "relation_type": "applies_concept",
                "metadata": {"confidence": 0.9},
            },
            {
                "source_document_id": "missing",
                "target_document_id": "concept-1",
                "relation_type": "applies_concept",
                "metadata": {},
            },
        ],
        wiki_version={
            "version": 4,
            "activated_at": datetime(2026, 7, 15, tzinfo=UTC),
        },
    )
    response = WikiGraphResponse.model_validate(payload)

    assert response.wiki_version == 4
    assert response.stats.node_count == 3
    assert response.stats.edge_count == 1
    assert response.stats.entity_count == 1
    assert response.stats.concept_count == 2
    assert response.stats.orphan_count == 1
    assert [node.degree for node in response.nodes] == [1, 1, 0]
    assert response.nodes[0].aliases == ["Obsidian alias"]
