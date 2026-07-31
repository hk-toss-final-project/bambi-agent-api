"""검토자 에이전트가 근거에 없는 서술을 잡아내는 정확도를 실제 LLM으로 측정한다.

정답을 아는 초안 30건(거짓 15 · 정상 15)을 검토시켜 두 지표를 잰다.

    거짓 탐지율 : 지어낸 초안 중 revise로 잡아낸 비율
    헛지적률    : 정상 초안 중 잘못 revise한 비율

두 지표를 같이 봐야 한다. 검토자를 엄격하게 하면 탐지율은 오르지만 헛지적이
늘어 재작성 비용만 커지기 때문이다.

**측정 범위 제한**: `search_pool` 도구는 빈 결과를 돌려주도록 대체한다.
DB 내용에 따라 결과가 달라지면 회귀 비교가 불가능하기 때문이다. 따라서 이
벤치마크는 `get_source` 기반 **인용 검증**을 측정하며, "빠진 사실 탐지"는
측정 대상이 아니다.

비용이 발생하므로 --confirm-cost를 명시해야 실행된다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import selectors
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parents[1]

# OPENAI_API_KEY를 .env에서 읽는다(다른 벤치마크와 같은 방식). import보다 먼저
# 호출해야 모듈 로딩 시점에 클라이언트를 만드는 경로에서도 키가 보인다.
load_dotenv(PROJECT_ROOT / ".env")

from agent.report_builder.features import critic  # noqa: E402
from agent.report_builder.features.critic import review_report  # noqa: E402
from shared.report_models import (  # noqa: E402
    GeneratedReportContent,
    ReportContextDocument,
)

DATASET = ROOT / "dataset.jsonl"


def load_cases() -> list[dict[str, object]]:
    """JSONL 벤치마크 데이터셋을 순서대로 읽는다."""
    return [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_contexts(case: dict[str, object]) -> list[ReportContextDocument]:
    """케이스의 근거 정의를 검토 대상 문서로 만든다."""
    return [
        ReportContextDocument(
            reference=str(source["ref"]),
            document_version_id=f"bench-{source['ref']}",
            chunk_id=f"bench-chunk-{source['ref']}",
            namespace_key="global" if str(source["ref"]).startswith("G") else "user/bench",
            title=str(source["title"]),
            content=str(source["content"]),
            url=None,
            score=1.0,
        )
        for source in case["sources"]  # type: ignore[union-attr]
    ]


def build_draft(case: dict[str, object]) -> GeneratedReportContent:
    """케이스의 초안 정의를 생성 콘텐츠로 만든다."""
    draft = case["draft"]  # type: ignore[index]
    return GeneratedReportContent(
        title=str(draft["title"]),
        summary=str(draft["summary"]),
        body=str(draft["body"]),
        citation_references=tuple(str(ref) for ref in draft["citation_refs"]),
    )


def estimate_input_tokens(cases: list[dict[str, object]]) -> int:
    """문자수 4자당 1 Token 가정으로 대략적인 입력량을 계산한다.

    검토자는 도구를 여러 번 부르며 같은 대화를 다시 보내므로, 케이스 본문의
    약 4배를 왕복한다고 보고 잡는다.
    """
    characters = sum(len(json.dumps(case, ensure_ascii=False)) for case in cases)
    return max(1, characters // 4 * 4)


async def _empty_search(connection: object, **kwargs: object) -> list[object]:
    """search_pool 도구가 항상 빈 결과를 돌려주게 한다(재현성 확보)."""
    return []


async def run_cases(
    cases: list[dict[str, object]], model: str
) -> list[dict[str, object]]:
    """모든 케이스를 검토시키고 판정·비용을 기록한다."""
    results: list[dict[str, object]] = []
    for case in cases:
        started = time.perf_counter()
        verdict = await review_report(
            None,  # type: ignore[arg-type]
            content=build_draft(case),
            contexts=build_contexts(case),
            user_id="bench-user",
            topic=str(case["topic"]),
            model=model,
        )
        expected = str(case["expect"])
        # unavailable(검토 불가)은 통과 처리되므로 pass로 집계한다.
        actual = "revise" if verdict.should_regenerate else "pass"
        results.append(
            {
                "id": case["id"],
                "kind": case["kind"],
                "expected": expected,
                "actual": actual,
                "correct": expected == actual,
                "outcome": verdict.outcome,
                "tool_calls": len(verdict.calls),
                "tools_used": [call.name for call in verdict.calls],
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "input_tokens": verdict.input_tokens,
                "output_tokens": verdict.output_tokens,
                "problem": verdict.problem,
            }
        )
        mark = "OK " if expected == actual else "MISS"
        print(
            f"[{mark}] {case['id']:<28} 기대={expected:<6} 실제={actual:<6} "
            f"도구={len(verdict.calls)}회",
            flush=True,
        )
    return results


def summarize(results: list[dict[str, object]]) -> dict[str, object]:
    """케이스별 결과를 집계 지표로 요약한다."""
    revise_cases = [r for r in results if r["expected"] == "revise"]
    pass_cases = [r for r in results if r["expected"] == "pass"]
    caught = sum(1 for r in revise_cases if r["correct"])
    false_flags = sum(1 for r in pass_cases if not r["correct"])
    total = len(results)
    return {
        "total": total,
        "correct": sum(1 for r in results if r["correct"]),
        "accuracy": round(sum(1 for r in results if r["correct"]) / total, 3),
        "revise_total": len(revise_cases),
        "detection_rate": round(caught / len(revise_cases), 3) if revise_cases else 0.0,
        "pass_total": len(pass_cases),
        "false_flag_rate": (
            round(false_flags / len(pass_cases), 3) if pass_cases else 0.0
        ),
        "unavailable": sum(1 for r in results if r["outcome"] == "unavailable"),
        "avg_tool_calls": round(
            sum(int(r["tool_calls"]) for r in results) / total, 2
        ),
        "avg_latency_ms": int(sum(int(r["latency_ms"]) for r in results) / total),
        "input_tokens": sum(int(r["input_tokens"]) for r in results),
        "output_tokens": sum(int(r["output_tokens"]) for r in results),
    }


def main() -> int:
    """비용 확인 후 전체 벤치마크를 실행하고 결과를 출력한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--confirm-cost", action="store_true")
    args = parser.parse_args()

    cases = load_cases()
    estimated = estimate_input_tokens(cases)
    print(f"cases={len(cases)}, estimated_input_tokens≈{estimated}")
    if not args.confirm_cost:
        print("실제 호출을 실행하려면 --confirm-cost를 추가하세요.")
        return 2

    # 재현성을 위해 창고 검색을 빈 결과로 고정한다(모듈 상단 설명 참고).
    critic.search_stored_documents = _empty_search  # type: ignore[assignment]

    results = asyncio.run(
        run_cases(cases, args.model),
        loop_factory=(
            (lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
            if sys.platform == "win32"
            else None
        ),
    )
    summary = summarize(results)
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n실패한 케이스:")
    for result in results:
        if not result["correct"]:
            print(f"  {result['id']} ({result['kind']}): {result['problem'][:100]}")
    (ROOT / "last_run.json").write_text(
        json.dumps(
            {"model": args.model, "summary": summary, "results": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
