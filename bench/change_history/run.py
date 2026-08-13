"""변경점(Change History) 추적 지연시간(Latency) 및 토큰 소비량 벤치마크.

비용이 발생하므로 예상 입력 Token과 비용을 먼저 표시하고 --confirm-cost를
명시한 경우에만 실행한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parents[1]

load_dotenv(PROJECT_ROOT / ".env")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from agent.change_history.api import chg_001  # noqa: E402
from agent.graph import build_report_generation_graph  # noqa: E402
from shared.report_models import ReportContextDocument  # noqa: E402

DATASET = ROOT / "dataset.jsonl"
RESULTS_DIR = ROOT / "results"


class _FakeConnection:
    """DB가 없을 때 무음 처리하는 Connection Stub."""

    async def transaction(self) -> Any:
        class _Tx:
            async def __aenter__(self) -> None:
                pass

            async def __aexit__(self, *args: Any) -> None:
                pass

        return _Tx()

    async def execute(self, *args: Any, **kwargs: Any) -> None:
        pass


def load_cases() -> list[dict[str, Any]]:
    """JSONL Benchmark 데이터셋을 순서대로 읽는다."""
    return [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_context_doc(item: dict[str, Any]) -> ReportContextDocument:
    """JSON 항목을 ReportContextDocument 객체로 만든다."""
    return ReportContextDocument(
        reference=str(item.get("reference") or "G1"),
        document_version_id=f"bench-{item.get('reference')}",
        chunk_id=f"bench-chunk-{item.get('reference')}",
        namespace_key="global",
        title=str(item.get("title") or "제목"),
        content=str(item.get("content") or ""),
        url=None,
        score=1.0,
    )


async def run_benchmark_case(
    connection: Any, case: dict[str, Any], model: str
) -> dict[str, Any]:
    """단일 케이스에 대해 지연시간과 결과를 측정한다."""
    case_type = case.get("type", "single")
    started = time.perf_counter()

    if case_type == "single":
        contexts = [build_context_doc(ctx) for ctx in case.get("contexts", [])]
        outcome = await chg_001(
            connection,
            user_id="bench-user",
            job_id=f"bench-{case['id']}",
            topic=str(case["topic"]),
            contexts=contexts,
            model=model,
            reference_date=date(2026, 8, 11),
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "id": case["id"],
            "type": case_type,
            "latency_ms": elapsed_ms,
            "fact_count": outcome.get("fact_count", 0),
            "input_tokens": outcome.get("input_tokens", 0),
            "output_tokens": outcome.get("output_tokens", 0),
            "diff_attempts": outcome.get("diff_attempts", 0),
            "compose_attempts": outcome.get("compose_attempts", 0),
            "impact_attempts": outcome.get("impact_attempts", 0),
        }
    else:
        # multi-topic report generation graph benchmark
        topics = [str(t) for t in case.get("topics", [])]
        contexts_by_topic = {
            t: [build_context_doc(ctx) for ctx in case.get("contexts_by_topic", {}).get(t, [])]
            for t in topics
        }
        all_contexts = [doc for docs in contexts_by_topic.values() for doc in docs]
        graph = build_report_generation_graph(connection)
        state = await graph.ainvoke(
            {
                "user_id": "bench-user",
                "job_id": f"bench-{case['id']}",
                "topic": str(case["topic"]),
                "topics": topics,
                "model": model,
                "content_type": "summary",
                "language": "ko",
                "change_history_enabled": True,
                "contexts": all_contexts,
                "contexts_by_topic": contexts_by_topic,
                "covered_topics": topics,
            }
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        chg_summary = state.get("change_history") or {}
        return {
            "id": case["id"],
            "type": case_type,
            "latency_ms": elapsed_ms,
            "fact_count": chg_summary.get("fact_count", 0),
            "input_tokens": chg_summary.get("input_tokens", 0),
            "output_tokens": chg_summary.get("output_tokens", 0),
        }


async def main_async() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--confirm-cost", action="store_true")
    parser.add_argument("--save-as", type=str, help="결과를 저장할 파일명 (예: baseline)")
    args = parser.parse_args()

    cases = load_cases()
    print(f"Benchmark Cases: {len(cases)}, Model: {args.model}")
    if not args.confirm_cost:
        print("실제 LLM 호출을 수행하려면 --confirm-cost 옵션을 추가하세요.")
        return 2

    dsn = os.getenv("AGENT_DATABASE_URL", "").strip()
    if dsn:
        print("AGENT_DATABASE_URL 연결하여 벤치마크를 실행합니다...")
        conn_ctx = await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row)
    else:
        print("DB 연결 정보가 없어 Stub Connection으로 실행합니다...")
        conn_ctx = _FakeConnection()

    try:
        results: list[dict[str, Any]] = []
        for case in cases:
            print(f"Running case: {case['id']} ...", end=" ", flush=True)
            res = await run_benchmark_case(conn_ctx, case, args.model)
            print(f"Done in {res['latency_ms']}ms (Tokens: in={res['input_tokens']}, out={res['output_tokens']})")
            results.append(res)
    finally:
        if hasattr(conn_ctx, "close"):
            await conn_ctx.close()

    total_latency = sum(r["latency_ms"] for r in results)
    print("\n=== Benchmark Results Summary ===")
    for r in results:
        print(f"- {r['id']} ({r['type']}): {r['latency_ms']} ms | in_tokens: {r['input_tokens']} | out_tokens: {r['output_tokens']}")
    print(f"Total Latency: {total_latency} ms")

    if args.save_as:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out_file = RESULTS_DIR / f"{args.save_as}.json"
        out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Results saved to {out_file}")

    return 0


def main() -> int:
    import selectors
    return asyncio.run(
        main_async(),
        loop_factory=(
            (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
            if sys.platform == "win32"
            else None
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
