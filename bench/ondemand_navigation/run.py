"""온디맨드 Wiki 1-hop·2-hop 정책을 무상 비교하는 결정적 벤치마크.

실제 DB·Embedding·LLM을 호출하지 않고 같은 10개 Wiki Graph에서 두 정책의
Page recall·precision·깊이·지연을 비교한다. 보고서 문장과 Citation 품질을 보는
Provider 벤치마크는 별도 비용 승인을 받은 뒤 실행해야 한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from domain.personal_wiki.navigation.features import traversal
from shared.wiki_navigation_policy import (
    ON_DEMAND_2HOP_WIKI_NAVIGATION_POLICY,
    WikiNavigationBudget,
)

ROOT = Path(__file__).resolve().parent
BASELINE_BUDGET = WikiNavigationBudget(
    max_depth=1,
    max_seed_pages=2,
    max_pages=6,
    max_chunks=12,
    hop_page_limits=(4,),
)


class _Connection:
    """WNAV-003의 Transaction 계약만 제공하는 무상 Connection 대역."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """저장 작업 없는 비동기 Transaction 문맥을 제공한다."""
        yield


def _args() -> argparse.Namespace:
    """선택적인 Markdown 출력 경로를 읽는다."""
    parser = argparse.ArgumentParser(
        description="Deterministic on-demand Wiki 1-hop vs 2-hop benchmark"
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _load_cases() -> list[dict[str, Any]]:
    """최소 10개 평가 Graph를 JSONL에서 읽는다."""
    cases = [
        json.loads(line)
        for line in (ROOT / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(cases) < 10:
        raise ValueError("온디맨드 탐색 벤치마크는 최소 10개 케이스가 필요합니다.")
    return cases


def _relation_rows(case: dict[str, Any]) -> list[dict[str, object]]:
    """간결한 Edge 목록을 실제 WNAV-003 저장소 Row 형태로 바꾼다."""
    rows: list[dict[str, object]] = []
    for index, raw in enumerate(case["edges"], start=1):
        source, target, confidence = raw
        rows.append(
            {
                "relation_id": f"{case['id']}-relation-{index}",
                "source_document_id": str(source),
                "target_document_id": str(target),
                "relation_type": "associated_with",
                "provenance_kind": "source_explicit",
                "confidence": float(confidence),
                "review_status": "accepted",
                "rationale": "결정적 벤치마크 관계",
                "supports": [
                    {
                        "source_document_version_id": f"source-{case['id']}",
                        "provenance_kind": "source_explicit",
                        "confidence": float(confidence),
                        "review_status": "accepted",
                        "evidence": "벤치마크 근거",
                        "rationale": "결정적 벤치마크 support",
                    }
                ],
            }
        )
    return rows


async def _execute_policy(
    case: dict[str, Any], budget: WikiNavigationBudget
) -> dict[str, object]:
    """한 Graph에서 지정 정책의 WNAV-003 결과와 소요 시간을 측정한다."""
    started = perf_counter()
    result = await traversal.wnav_003(
        _Connection(),  # type: ignore[arg-type]
        user_id=f"benchmark-{case['id']}",
        seed_document_ids=[str(value) for value in case["seeds"]],
        max_depth=budget.max_depth,
        max_pages=budget.max_pages,
        seed_page_limit=budget.max_seed_pages,
        hop_page_limits=budget.hop_page_limits,
    )
    return {
        "documents": list(result.document_ids),
        "document_hops": dict(result.document_hops),
        "relations": len(result.relations),
        "truncated": result.truncated,
        "latency_ms": (perf_counter() - started) * 1000,
    }


def _metrics(case: dict[str, Any], run: dict[str, object]) -> dict[str, float]:
    """Page recall·precision과 금지 Page 채택 수를 계산한다."""
    documents = set(str(value) for value in run["documents"])  # type: ignore[union-attr]
    relevant = set(str(value) for value in case["relevant"])
    forbidden = set(str(value) for value in case.get("forbidden") or ())
    return {
        "recall": len(documents & relevant) / len(relevant),
        "precision": len(documents & relevant) / len(documents),
        "forbidden": float(len(documents & forbidden)),
    }


async def _run_case(case: dict[str, Any]) -> dict[str, object]:
    """저장소 함수를 Graph Fixture로 바꿔 두 정책을 같은 입력에서 비교한다."""
    rows = _relation_rows(case)

    async def fake_scope(*args: object, **kwargs: object) -> None:
        """결정적 벤치마크에서는 RLS 설정을 생략한다."""

    async def fake_relations(
        connection: object, *, document_ids: list[str], **kwargs: object
    ) -> list[dict[str, object]]:
        """현재 Frontier와 맞닿은 Fixture 관계만 반환한다."""
        frontier = set(document_ids)
        return [
            row
            for row in rows
            if str(row["source_document_id"]) in frontier
            or str(row["target_document_id"]) in frontier
        ]

    original_scope = traversal.set_personal_wiki_scope
    original_loader = traversal.load_wiki_navigation_relations
    traversal.set_personal_wiki_scope = fake_scope
    traversal.load_wiki_navigation_relations = fake_relations
    try:
        baseline = await _execute_policy(case, BASELINE_BUDGET)
        two_hop = await _execute_policy(
            case, ON_DEMAND_2HOP_WIKI_NAVIGATION_POLICY.budget
        )
    finally:
        traversal.set_personal_wiki_scope = original_scope
        traversal.load_wiki_navigation_relations = original_loader
    required = set(str(value) for value in case.get("required_2hop") or ())
    selected = set(str(value) for value in two_hop["documents"])  # type: ignore[union-attr]
    hops = two_hop["document_hops"]
    assert isinstance(hops, dict)
    baseline_metrics = _metrics(case, baseline)
    two_hop_metrics = _metrics(case, two_hop)
    return {
        "id": case["id"],
        "baseline": baseline,
        "two_hop": two_hop,
        "baseline_metrics": baseline_metrics,
        "two_hop_metrics": two_hop_metrics,
        "success": (
            required.issubset(selected)
            and two_hop_metrics["forbidden"] == 0
            and len(selected) <= ON_DEMAND_2HOP_WIKI_NAVIGATION_POLICY.budget.max_pages
            and max((int(value) for value in hops.values()), default=0) <= 2
        ),
    }


def _mean(rows: list[dict[str, object]], path: tuple[str, str]) -> float:
    """중첩 실행 결과의 숫자 지표 평균을 반환한다."""
    return sum(float(row[path[0]][path[1]]) for row in rows) / len(rows)  # type: ignore[index]


def _markdown(rows: list[dict[str, object]]) -> str:
    """정책별 품질·지연 집계와 케이스 결과를 Markdown으로 만든다."""
    baseline_recall = _mean(rows, ("baseline_metrics", "recall"))
    two_hop_recall = _mean(rows, ("two_hop_metrics", "recall"))
    baseline_precision = _mean(rows, ("baseline_metrics", "precision"))
    two_hop_precision = _mean(rows, ("two_hop_metrics", "precision"))
    improved = sum(
        int(
            float(row["two_hop_metrics"]["recall"])  # type: ignore[index]
            > float(row["baseline_metrics"]["recall"])  # type: ignore[index]
        )
        for row in rows
    )
    lines = [
        "# 온디맨드 Wiki 1-hop·2-hop 결정적 비교",
        "",
        f"- 실행일: {datetime.now(UTC).date().isoformat()}",
        "- 모델·Provider: 없음(결정적 WNAV-003 경로)",
        "- Token·비용: 0",
        f"- 성공: {sum(int(bool(row['success'])) for row in rows)}/{len(rows)}",
        f"- 평균 Page Recall: 1-hop {baseline_recall:.3f} → 2-hop {two_hop_recall:.3f}",
        f"- 평균 Page Precision: 1-hop {baseline_precision:.3f} → 2-hop {two_hop_precision:.3f}",
        f"- Recall 개선 케이스: {improved}/{len(rows)}",
        f"- 평균 순회 지연: 1-hop {_mean(rows, ('baseline', 'latency_ms')):.3f}ms → "
        f"2-hop {_mean(rows, ('two_hop', 'latency_ms')):.3f}ms",
        "",
        "| 케이스 | 성공 | 1-hop 문서 | 2-hop 문서 | Recall | Precision |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        baseline = row["baseline"]
        two_hop = row["two_hop"]
        baseline_metrics = row["baseline_metrics"]
        two_hop_metrics = row["two_hop_metrics"]
        lines.append(
            f"| {row['id']} | {'Y' if row['success'] else 'N'} | "
            f"{len(baseline['documents'])} | {len(two_hop['documents'])} | "  # type: ignore[index]
            f"{float(baseline_metrics['recall']):.2f}→{float(two_hop_metrics['recall']):.2f} | "  # type: ignore[index]
            f"{float(baseline_metrics['precision']):.2f}→{float(two_hop_metrics['precision']):.2f} |"  # type: ignore[index]
        )
    return "\n".join(lines) + "\n"


async def _run() -> int:
    """전체 케이스를 비교하고 선택적으로 결과 파일을 저장한다."""
    args = _args()
    rows = [await _run_case(case) for case in _load_cases()]
    report = _markdown(rows)
    print(report, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    baseline_recall = _mean(rows, ("baseline_metrics", "recall"))
    two_hop_recall = _mean(rows, ("two_hop_metrics", "recall"))
    return 0 if all(bool(row["success"]) for row in rows) and two_hop_recall >= baseline_recall else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
