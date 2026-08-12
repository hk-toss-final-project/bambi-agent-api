"""모델별 개인 Wiki 지식그래프를 뷰어용 JSON으로 익스포트한다.

wiki_documents(entity·concept 노드)와 wiki_document_relations(엣지)를 조회해
force-graph 뷰어가 바로 읽을 수 있는 {nodes, links, stats} 구조로 저장한다.
노드 라벨·요약은 최신 wiki_document_versions.title/summary에서 가져온다.
RLS 때문에 조회 전 사용자 Scope를 설정한다(persistence 함수와 동일 방식).

실행:
  uv run python scripts/model_wiki_eval/export_model_graph.py \
      --user-id model-eval-4o-mini --model gpt-4o-mini --out graphs/4o-mini.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.config import load_settings
from infrastructure.persistence.api import set_personal_wiki_scope

type DictRow = dict[str, Any]

NODE_QUERY = """
SELECT
    d.id::text AS id,
    d.document_kind AS kind,
    d.document_key AS key,
    d.domain AS domain,
    v.title AS title,
    v.summary AS summary
FROM agent.wiki_documents d
LEFT JOIN LATERAL (
    SELECT title, summary
    FROM agent.wiki_document_versions
    WHERE document_id = d.id
    ORDER BY version DESC
    LIMIT 1
) v ON TRUE
WHERE d.namespace_key = %s
  AND d.deleted_at IS NULL
  AND d.document_kind IN ('entity', 'concept')
"""

EDGE_QUERY = """
SELECT
    source_document_id::text AS source,
    target_document_id::text AS target,
    relation_type AS type,
    confidence::float AS confidence,
    review_status AS review_status,
    status AS status
FROM agent.wiki_document_relations
WHERE namespace_key = %s
  AND status = 'active'
"""


async def export_graph(database_url: str, user_id: str, model: str) -> dict[str, Any]:
    """한 사용자의 Wiki 그래프를 조회해 뷰어용 구조로 반환한다."""
    namespace_key = f"user/{user_id}"
    connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
        database_url, row_factory=dict_row
    )
    try:
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=user_id)
            node_cursor = await connection.execute(NODE_QUERY, (namespace_key,))
            node_rows = await node_cursor.fetchall()
            edge_cursor = await connection.execute(EDGE_QUERY, (namespace_key,))
            edge_rows = await edge_cursor.fetchall()
            # 소스 클리핑(원본 문서) 수도 함께 보고한다.
            src_cursor = await connection.execute(
                "SELECT count(*) AS n FROM agent.user_source_document_versions "
                "WHERE namespace_key = %s",
                (namespace_key,),
            )
            source_count = (await src_cursor.fetchone())["n"]
    finally:
        await connection.close()

    valid_ids = {row["id"] for row in node_rows}
    nodes = [
        {
            "id": row["id"],
            "kind": row["kind"],
            "label": row["title"] or row["key"],
            "key": row["key"],
            "domain": row["domain"],
            "summary": row["summary"],
        }
        for row in node_rows
    ]
    # 삭제/누락 노드를 참조하는 엣지는 제외한다.
    links = [
        {
            "source": row["source"],
            "target": row["target"],
            "type": row["type"],
            "confidence": round(row["confidence"], 3),
            "review_status": row["review_status"],
        }
        for row in edge_rows
        if row["source"] in valid_ids and row["target"] in valid_ids
    ]

    # 연결 차수 계산(뷰어에서 노드 크기로 사용)
    degree: Counter[str] = Counter()
    for link in links:
        degree[link["source"]] += 1
        degree[link["target"]] += 1
    for node in nodes:
        node["degree"] = degree.get(node["id"], 0)

    kind_counts = Counter(node["kind"] for node in nodes)
    domain_counts = Counter(node["domain"] for node in nodes if node["domain"])
    type_counts = Counter(link["type"] for link in links)
    accepted = sum(1 for link in links if link["review_status"] == "accepted")
    isolated = sum(1 for node in nodes if node["degree"] == 0)

    stats = {
        "source_documents": source_count,
        "nodes": len(nodes),
        "entities": kind_counts.get("entity", 0),
        "concepts": kind_counts.get("concept", 0),
        "edges": len(links),
        "accepted_edges": accepted,
        "accepted_ratio": round(accepted / len(links), 3) if links else 0.0,
        "isolated_nodes": isolated,
        "avg_degree": round(sum(degree.values()) / len(nodes), 2) if nodes else 0.0,
        "relation_types": dict(type_counts),
        "domains": dict(domain_counts.most_common()),
    }

    return {"model": model, "user_id": user_id, "stats": stats, "nodes": nodes, "links": links}


def main() -> int:
    """CLI 인자를 해석하고 그래프 익스포트를 실행한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    settings = load_settings()
    if not settings.agent_database_url:
        print("AGENT_DATABASE_URL이 설정되지 않았습니다.", file=sys.stderr)
        return 2

    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        graph = runner.run(
            export_graph(settings.agent_database_url, args.user_id, args.model)
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(graph["stats"], ensure_ascii=False, indent=2))
    print(f"\n그래프 저장: {args.out} (노드 {graph['stats']['nodes']}, 엣지 {graph['stats']['edges']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
