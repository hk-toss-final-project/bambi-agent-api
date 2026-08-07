"""관심사 범주 묶음의 루트 집중도·연결 관점·인용 품질을 실제 LLM으로 평가한다.

실제 API 비용이 발생하므로 예상 토큰과 비용을 먼저 출력하고, --confirm-cost를
명시한 경우에만 전체 케이스를 실행해 results/에 결과를 기록한다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parents[1]
DATASET = ROOT / "dataset.jsonl"
RESULTS = ROOT / "results"

load_dotenv(PROJECT_ROOT / ".env")
sys.path.insert(0, str(PROJECT_ROOT))

from agent.llm.api import complete_with_usage  # noqa: E402
from agent.report_builder.features import generation  # noqa: E402
from shared.report_models import ReportContextDocument  # noqa: E402


def load_cases() -> list[dict[str, Any]]:
    """JSONL 데이터셋을 순서대로 읽고 최소 케이스 수를 검증한다."""
    cases = [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(cases) < 10:
        raise ValueError("관심사 범주 리포트 벤치마크는 최소 10개 케이스가 필요합니다.")
    return cases


def estimate_tokens(cases: list[dict[str, Any]]) -> tuple[int, int]:
    """프롬프트 고정분과 데이터셋 문자 수로 입력·출력 토큰을 보수적으로 추정한다."""
    characters = sum(len(json.dumps(case, ensure_ascii=False)) for case in cases)
    input_tokens = len(cases) * 1_000 + characters // 4
    output_tokens = len(cases) * 800
    return input_tokens, output_tokens


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    *,
    input_cost_per_million: float,
    output_cost_per_million: float,
) -> float:
    """토큰 수와 CLI 단가로 예상·실제 비용을 달러로 계산한다."""
    return (
        input_tokens * input_cost_per_million
        + output_tokens * output_cost_per_million
    ) / 1_000_000


def build_contexts(case: dict[str, Any]) -> list[ReportContextDocument]:
    """루트·연결 노드·최신 자료를 안정 참조가 붙은 생성 근거로 만든다."""
    contexts = [
        ReportContextDocument(
            reference="P1",
            document_version_id="root-version",
            chunk_id="root-chunk",
            namespace_key="user/benchmark",
            title=str(case["root"]),
            content=str(case["root_context"]),
            url=None,
            score=1.0,
        )
    ]
    for index, (keyword, content) in enumerate(
        zip(case["neighbors"], case["neighbor_contexts"], strict=True), start=2
    ):
        contexts.append(
            ReportContextDocument(
                reference=f"P{index}",
                document_version_id=f"neighbor-version-{index}",
                chunk_id=f"neighbor-chunk-{index}",
                namespace_key="user/benchmark",
                title=str(keyword),
                content=str(content),
                url=None,
                score=0.9,
            )
        )
    contexts.append(
        ReportContextDocument(
            reference="G1",
            document_version_id="global-version",
            chunk_id="global-chunk",
            namespace_key="global",
            title="Latest Source",
            content=str(case["global_context"]),
            url="https://example.com/latest",
            score=0.8,
        )
    )
    return contexts


def current_revision() -> str:
    """결과 재현에 쓸 현재 Git 짧은 커밋 해시를 반환한다."""
    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def evaluate_case(case: dict[str, Any], *, model: str) -> dict[str, Any]:
    """케이스 하나를 생성하고 루트·연결 관점·Citation 기준으로 채점한다."""
    usage = {"input_tokens": 0, "output_tokens": 0}
    original_complete = generation.complete

    def tracked_complete(system_prompt: str, user_prompt: str, model: str) -> str:
        """생성 호출의 실제 토큰 사용량을 누적한다."""
        result = complete_with_usage(system_prompt, user_prompt, model=model)
        usage["input_tokens"] += result.input_tokens
        usage["output_tokens"] += result.output_tokens
        return result.text

    generation.complete = tracked_complete
    started = time.perf_counter()
    try:
        generated = generation.generate_report_content(
            topic=str(case["root"]),
            content_type="interest_news_card",
            language=str(case["language"]),
            contexts=build_contexts(case),
            model=model,
            interest_bundle={
                "root": {"keyword": case["root"]},
                "neighbors": [
                    {"keyword": keyword} for keyword in case["neighbors"]
                ],
            },
        )
    finally:
        generation.complete = original_complete
    latency_ms = int((time.perf_counter() - started) * 1_000)
    combined = f"{generated.title}\n{generated.summary}\n{generated.body}".casefold()
    root_terms = [str(term).casefold() for term in case["required_root_terms"]]
    neighbor_terms = [
        str(term).casefold() for term in case["required_neighbor_terms"]
    ]
    root_focus = any(term in generated.title.casefold() for term in root_terms) and any(
        term in generated.summary.casefold() for term in root_terms
    )
    neighbor_hits = sum(term in combined for term in neighbor_terms)
    citations = set(generated.citation_references)
    required_refs = set(case["required_refs"])
    neighbor_headings = sum(
        bool(re.search(rf"(?im)^#+\s+.*{re.escape(term)}", generated.body))
        for term in neighbor_terms
    )
    checks = {
        "root_focus": root_focus,
        "neighbor_coverage": neighbor_hits >= int(case["min_neighbor_terms"]),
        "required_citations": required_refs <= citations,
        "integrated_structure": neighbor_headings == 0,
    }
    return {
        "id": case["id"],
        "passed": all(checks.values()),
        "checks": checks,
        "title": generated.title,
        "citations": list(generated.citation_references),
        "latency_ms": latency_ms,
        **usage,
    }


def write_result(
    results: list[dict[str, Any]],
    *,
    model: str,
    revision: str,
    input_cost_per_million: float,
    output_cost_per_million: float,
) -> Path:
    """케이스별 결과와 집계·비용·이전 결과 비교를 Markdown으로 기록한다."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    safe_model = model.replace("/", "-")
    path = RESULTS / f"{now.date().isoformat()}_{safe_model}.md"
    previous = sorted(RESULTS.glob("*.md"))
    previous_label = previous[-1].name if previous else "없음(최초 실행)"
    passed = sum(int(result["passed"]) for result in results)
    input_tokens = sum(int(result["input_tokens"]) for result in results)
    output_tokens = sum(int(result["output_tokens"]) for result in results)
    average_latency = sum(int(result["latency_ms"]) for result in results) / len(results)
    cost = calculate_cost(
        input_tokens,
        output_tokens,
        input_cost_per_million=input_cost_per_million,
        output_cost_per_million=output_cost_per_million,
    )
    lines = [
        "# 관심사 범주 리포트 벤치마크",
        "",
        f"- 실행 시각(UTC): {now.isoformat()}",
        f"- 모델: `{model}`",
        f"- 프롬프트 버전(커밋): `{revision}`",
        f"- 성공: {passed}/{len(results)} ({passed / len(results):.1%})",
        f"- 평균 지연: {average_latency:.0f}ms",
        f"- 토큰: 입력 {input_tokens}, 출력 {output_tokens}",
        f"- 비용: ${cost:.6f} (입력 ${input_cost_per_million}/M, 출력 ${output_cost_per_million}/M)",
        f"- 이전 결과: {previous_label}",
        "",
        "| 케이스 | 결과 | 루트 | 연결 | 인용 | 통합 구조 | 지연(ms) | 입력/출력 토큰 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        checks = result["checks"]
        lines.append(
            f"| {result['id']} | {'PASS' if result['passed'] else 'FAIL'} "
            f"| {checks['root_focus']} | {checks['neighbor_coverage']} "
            f"| {checks['required_citations']} | {checks['integrated_structure']} "
            f"| {result['latency_ms']} "
            f"| {result['input_tokens']}/{result['output_tokens']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    """비용을 확인한 실행만 허용하고 전체 데이터셋 결과를 기록한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--confirm-cost", action="store_true")
    parser.add_argument("--input-cost-per-million", type=float, default=0.40)
    parser.add_argument("--output-cost-per-million", type=float, default=1.60)
    args = parser.parse_args()
    cases = load_cases()
    estimated_input, estimated_output = estimate_tokens(cases)
    estimated_cost = calculate_cost(
        estimated_input,
        estimated_output,
        input_cost_per_million=args.input_cost_per_million,
        output_cost_per_million=args.output_cost_per_million,
    )
    print(
        f"cases={len(cases)}, estimated_input_tokens={estimated_input}, "
        f"estimated_output_tokens={estimated_output}, estimated_cost=${estimated_cost:.6f}"
    )
    if not args.confirm_cost:
        print("실제 호출을 실행하려면 비용 승인 후 --confirm-cost를 추가하세요.")
        return 2
    results = [evaluate_case(case, model=args.model) for case in cases]
    path = write_result(
        results,
        model=args.model,
        revision=current_revision(),
        input_cost_per_million=args.input_cost_per_million,
        output_cost_per_million=args.output_cost_per_million,
    )
    print(f"result={path}")
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
