"""변경점(Delta) 판정 품질 벤치마크 — 신규·갱신·중복 분류와 이름표 안정성을 잰다.

`bench/change_history`는 **지연시간**을 재는 벤치다. 이 벤치는 다른 것을 잰다.
같은 사실이 표현만 바뀌어 다시 들어왔을 때 갱신으로 잘못 판정하는지, 값이 진짜
달라졌을 때 놓치는지, 이름표에 날짜·회차를 박아 다음 실행의 대조를 끊는지를 본다.

케이스마다 과거 팩트(base_facts)를 델타 테이블에 먼저 심고 오늘 자료를 넣어
`chg_001`을 돌린 뒤, 나온 판정을 기대값과 대조한다. 케이스 사이에 기록이 새지
않도록 실행 전에 벤치 전용 사용자의 팩트를 지운다.

**정확한 문자열 일치로 채점하지 않는다.** LLM이 고르는 subject·attribute 표현은
실행마다 흔들리는데 그 흔들림 자체는 품질 문제가 아니다. 대신 "갱신이 나왔는가",
"신규가 나왔는가", "이름표가 안정적인가"처럼 이 기능이 실제로 약속한 것만 센다.

비용이 발생하므로 예상 비용을 먼저 표시하고 --confirm-cost를 준 경우에만 실행한다.

실행:
    uv run python bench/delta_verdict/run.py --confirm-cost --save-as 2026-08-13_gpt-4o-mini
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import selectors
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

from agent.change_history.api import chg_001, find_drifting_marker  # noqa: E402
from infrastructure.persistence.api import (  # noqa: E402
    persist_change_history_run,
    set_personal_wiki_scope,
)
from shared.change_history_models import NewChangeHistoryFact  # noqa: E402
from shared.report_models import ReportContextDocument  # noqa: E402

DATASET = ROOT / "dataset.jsonl"
RESULTS_DIR = ROOT / "results"

# 벤치 전용 사용자. 실행마다 이 사용자의 델타 기록을 지우고 다시 심는다.
BENCH_USER_ID = "bench-delta-verdict"

# 기준일을 고정한다 — "오늘"에 따라 결과가 흔들리면 어제 기록과 비교할 수 없다.
REFERENCE_DATE = date(2026, 8, 11)

# 예상 비용 안내용 단가(1M 토큰당 USD). 실제 청구 단가는 계약에 따라 다르다.
DEFAULT_INPUT_RATE = 0.40
DEFAULT_OUTPUT_RATE = 1.60

# 케이스당 대략적인 입력 토큰. 이전 실행 실측(4,000~5,000)에서 잡았다.
ESTIMATED_INPUT_TOKENS_PER_CASE = 5000
ESTIMATED_OUTPUT_TOKENS_PER_CASE = 450


def load_cases() -> list[dict[str, Any]]:
    """JSONL 데이터셋을 순서대로 읽는다."""
    return [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_context_doc(item: dict[str, Any]) -> ReportContextDocument:
    """데이터셋의 근거 항목을 ReportContextDocument로 만든다."""
    reference = str(item.get("reference") or "G1")
    return ReportContextDocument(
        reference=reference,
        document_version_id=f"bench-{reference}",
        chunk_id=f"bench-chunk-{reference}",
        namespace_key="global",
        title=str(item.get("title") or "제목"),
        content=str(item.get("content") or ""),
        url=None,
        score=1.0,
    )


async def reset_bench_facts(connection: Any) -> None:
    """벤치 사용자의 델타 기록을 모두 지운다.

    케이스마다 과거 팩트를 새로 심으므로, 이전 케이스나 이전 실행의 기록이 남아
    있으면 대조 대상이 섞여 채점이 무의미해진다.
    """
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=BENCH_USER_ID)
        await connection.execute(
            "DELETE FROM agent.change_history_facts WHERE user_id = %s",
            (BENCH_USER_ID,),
        )
        await connection.execute(
            "DELETE FROM agent.change_history_runs WHERE user_id = %s",
            (BENCH_USER_ID,),
        )


async def seed_base_facts(
    connection: Any, *, topic: str, base_facts: list[dict[str, Any]]
) -> None:
    """케이스가 지정한 과거 팩트를 델타 테이블에 심는다."""
    if not base_facts:
        return
    facts = [
        NewChangeHistoryFact(
            subject=str(item["subject"]),
            attribute=str(item["attribute"]),
            fact_value=str(item.get("fact_value") or ""),
            statement=str(item["statement"]),
            verdict="new",
            source_reference="G1",
        )
        for item in base_facts
    ]
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=BENCH_USER_ID)
        await persist_change_history_run(
            connection,
            user_id=BENCH_USER_ID,
            topic=topic,
            reference_date=REFERENCE_DATE,
            facts=facts,
            is_first_run=True,
            outcome="delta",
        )


def score_case(case: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    """한 케이스의 산출물을 기대값과 대조해 통과 여부와 사유를 만든다.

    Args:
        case: 데이터셋 케이스
        outcome: chg_001 반환값

    Returns:
        판정 수치와 실패 사유가 담긴 채점 결과
    """
    facts = list(outcome.get("facts") or [])
    updated = [item for item in facts if item.fact.verdict == "updated"]
    new = [item for item in facts if item.fact.verdict == "new"]
    unstable = [
        item.fact.attribute
        for item in facts
        if find_drifting_marker(item.fact.attribute)
    ]

    expected = case.get("expected") or {}
    failures: list[str] = []
    if "updated_max" in expected and len(updated) > int(expected["updated_max"]):
        failures.append(
            f"갱신이 {len(updated)}건 나왔다(허용 {expected['updated_max']}건). 재서술을 변경으로 판정했다."
        )
    if "updated_min" in expected and len(updated) < int(expected["updated_min"]):
        failures.append(
            f"갱신이 {len(updated)}건뿐이다(최소 {expected['updated_min']}건). 진짜 변경을 놓쳤다."
        )
    if "new_min" in expected and len(new) < int(expected["new_min"]):
        failures.append(f"신규가 {len(new)}건뿐이다(최소 {expected['new_min']}건).")
    if expected.get("stable_attributes") and unstable:
        failures.append(f"이름표에 시점·순번이 박혔다: {unstable}")

    return {
        "id": case["id"],
        "category": case["category"],
        "passed": not failures,
        "failures": failures,
        "updated_count": len(updated),
        "new_count": len(new),
        "duplicate_count": int(outcome.get("duplicate_count") or 0),
        "unstable_attributes": unstable,
        "attributes": [item.fact.attribute for item in facts],
        "diff_attempts": int(outcome.get("diff_attempts") or 0),
        "input_tokens": int(outcome.get("input_tokens") or 0),
        "output_tokens": int(outcome.get("output_tokens") or 0),
    }


async def run_case(connection: Any, case: dict[str, Any], model: str) -> dict[str, Any]:
    """과거 팩트를 심고 오늘 자료로 델타를 돌린 뒤 채점한다."""
    topic = str(case["topic"])
    await reset_bench_facts(connection)
    await seed_base_facts(
        connection, topic=topic, base_facts=list(case.get("base_facts") or [])
    )
    contexts = [build_context_doc(ctx) for ctx in case.get("contexts", [])]
    started = time.perf_counter()
    outcome = await chg_001(
        connection,
        user_id=BENCH_USER_ID,
        job_id=f"bench-{case['id']}",
        topic=topic,
        contexts=contexts,
        model=model,
        reference_date=REFERENCE_DATE,
    )
    result = score_case(case, outcome)
    result["latency_ms"] = int((time.perf_counter() - started) * 1000)
    return result


def summarize(results: list[dict[str, Any]], *, model: str, rates: tuple[float, float]) -> str:
    """케이스별 결과와 집계 지표를 Markdown 보고서로 만든다."""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    input_tokens = sum(r["input_tokens"] for r in results)
    output_tokens = sum(r["output_tokens"] for r in results)
    latency = sum(r["latency_ms"] for r in results)
    reworked = sum(1 for r in results if r["diff_attempts"] > 1)
    unstable_cases = [r["id"] for r in results if r["unstable_attributes"]]
    cost = input_tokens / 1_000_000 * rates[0] + output_tokens / 1_000_000 * rates[1]

    by_category: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        by_category.setdefault(row["category"], []).append(row)

    lines = [
        "# 델타 판정 품질 벤치마크 결과",
        "",
        f"- 실행일: {date.today().isoformat()}",
        f"- 모델: {model}",
        f"- 기준일(고정): {REFERENCE_DATE.isoformat()}",
        f"- 케이스: {total}건",
        "",
        "## 집계",
        "",
        f"- 정확도: {passed}/{total} ({passed / total * 100:.1f}%)",
        f"- 평균 지연시간: {latency / total / 1000:.2f}s",
        f"- 토큰: 입력 {input_tokens:,} / 출력 {output_tokens:,}",
        f"- 예상 비용: ${cost:.4f} (입력 ${rates[0]}/1M, 출력 ${rates[1]}/1M 기준)",
        f"- diff 재작업 발생: {reworked}/{total}건",
        f"- 이름표에 시점·순번이 박힌 케이스: {len(unstable_cases)}건 {unstable_cases or ''}",
        "",
        "## 분류별 정확도",
        "",
        "| 분류 | 통과 | 전체 |",
        "|---|---|---|",
    ]
    for category, rows in sorted(by_category.items()):
        lines.append(
            f"| {category} | {sum(1 for r in rows if r['passed'])} | {len(rows)} |"
        )
    lines += [
        "",
        "## 케이스별 결과",
        "",
        "| 케이스 | 분류 | 결과 | 갱신 | 신규 | 중복 | 지연 | 사유 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in results:
        lines.append(
            "| {id} | {category} | {mark} | {updated_count} | {new_count} | "
            "{duplicate_count} | {latency:.1f}s | {reason} |".format(
                mark="PASS" if row["passed"] else "**FAIL**",
                latency=row["latency_ms"] / 1000,
                reason="; ".join(row["failures"]) or "-",
                **row,
            )
        )
    return "\n".join(lines) + "\n"


async def main_async() -> int:
    """비용 확인을 거쳐 전체 케이스를 실행하고 결과를 기록한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--confirm-cost", action="store_true")
    parser.add_argument("--save-as", type=str, help="results/ 아래 저장할 파일명")
    parser.add_argument("--only", type=str, help="이 id의 케이스만 실행한다")
    parser.add_argument("--input-rate", type=float, default=DEFAULT_INPUT_RATE)
    parser.add_argument("--output-rate", type=float, default=DEFAULT_OUTPUT_RATE)
    args = parser.parse_args()

    cases = load_cases()
    if args.only:
        cases = [case for case in cases if case["id"] == args.only]
        if not cases:
            print(f"해당 id의 케이스가 없습니다: {args.only}")
            return 2

    estimated_input = len(cases) * ESTIMATED_INPUT_TOKENS_PER_CASE
    estimated_output = len(cases) * ESTIMATED_OUTPUT_TOKENS_PER_CASE
    estimated_cost = (
        estimated_input / 1_000_000 * args.input_rate
        + estimated_output / 1_000_000 * args.output_rate
    )
    print(f"케이스 {len(cases)}건, 모델 {args.model}")
    print(
        f"예상 토큰: 입력 약 {estimated_input:,} / 출력 약 {estimated_output:,} "
        f"→ 예상 비용 약 ${estimated_cost:.4f}"
    )
    if not args.confirm_cost:
        print("실제 LLM을 호출하려면 --confirm-cost 를 붙이세요.")
        return 2

    dsn = os.getenv("AGENT_DATABASE_URL", "").strip()
    if not dsn:
        print("AGENT_DATABASE_URL 이 필요합니다 — 과거 팩트를 심어야 대조를 잴 수 있습니다.")
        return 2

    results: list[dict[str, Any]] = []
    async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as conn:
        for case in cases:
            print(f"[{case['id']}] 실행 중 ...", end=" ", flush=True)
            try:
                result = await run_case(conn, case, args.model)
            except Exception as error:  # noqa: BLE001 - 한 케이스 실패로 전체를 잃지 않는다
                print(f"실패: {type(error).__name__}: {error}")
                results.append(
                    {
                        "id": case["id"],
                        "category": case["category"],
                        "passed": False,
                        "failures": [f"실행 오류: {type(error).__name__}: {error}"],
                        "updated_count": 0,
                        "new_count": 0,
                        "duplicate_count": 0,
                        "unstable_attributes": [],
                        "attributes": [],
                        "diff_attempts": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "latency_ms": 0,
                    }
                )
                continue
            print(
                f"{'PASS' if result['passed'] else 'FAIL'} "
                f"(갱신 {result['updated_count']} / 신규 {result['new_count']}, "
                f"{result['latency_ms']}ms)"
            )
            results.append(result)
        await reset_bench_facts(conn)

    report = summarize(
        results, model=args.model, rates=(args.input_rate, args.output_rate)
    )
    print()
    print(report)

    if args.save_as:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / f"{args.save_as}.md").write_text(report, encoding="utf-8")
        (RESULTS_DIR / f"{args.save_as}.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"결과를 {RESULTS_DIR / args.save_as}.md / .json 에 저장했습니다.")
    return 0


def main() -> int:
    """Windows에서도 psycopg 비동기가 동작하도록 Selector 루프로 실행한다."""
    if sys.platform == "win32":
        return asyncio.run(
            main_async(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
