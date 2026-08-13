"""비긴급 Report Batch 초안의 구조·근거·Citation 품질 벤치마크 실행기.

OpenAI Batch 전송과 결과 재정렬은 결정적 단위 테스트로 검증한다. 이 실행기는
Batch와 동기 경로가 공유하는 고정 Prompt를 실제 모델로 호출해 품질을 측정한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from agent.llm.api import complete_with_usage
from agent.report_builder.features import quality
from agent.report_builder.features.batch import report_context_from_mapping
from agent.report_builder.features.generation import (
    build_report_generation_prompt,
    parse_report_generation,
)


@dataclass(slots=True)
class Usage:
    """벤치마크 전체 입력·출력 Token을 누적한다."""

    input_tokens: int = 0
    output_tokens: int = 0


def _args() -> argparse.Namespace:
    """모델·단가와 무료 추정 모드 인자를 파싱한다."""
    parser = argparse.ArgumentParser(description="Report batch generation benchmark")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--input-cost-per-million", type=float)
    parser.add_argument("--output-cost-per-million", type=float)
    parser.add_argument("--estimate-only", action="store_true")
    args = parser.parse_args()
    if not args.estimate_only and (
        args.input_cost_per_million is None or args.output_cost_per_million is None
    ):
        parser.error("실제 실행에는 입력·출력 백만 Token당 단가가 필요합니다.")
    return args


def _load_cases() -> list[dict[str, Any]]:
    """JSONL Report 평가 케이스를 순서대로 읽는다."""
    return [
        json.loads(line)
        for line in (ROOT / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _prompt(case: dict[str, Any], model: str) -> Any:
    """서비스와 같은 Prompt Builder로 평가 케이스 Prompt를 만든다."""
    contexts = [report_context_from_mapping(value) for value in case["contexts"]]
    return build_report_generation_prompt(
        topic=case["topic"],
        content_type=case["content_type"],
        language=case["language"],
        contexts=contexts,
        model=model,
    )


def _estimate_tokens(cases: list[dict[str, Any]], model: str) -> tuple[int, int]:
    """실행 승인 전에 볼 보수적인 입력·출력 Token 상한을 계산한다."""
    input_chars = sum(
        len(prompt.system_prompt) + len(prompt.user_prompt)
        for prompt in (_prompt(case, model) for case in cases)
    )
    return input_chars // 2 + 1, len(cases) * 2_000


def _score(generated: Any, expected: dict[str, Any], context_count: int) -> list[str]:
    """본문 핵심어·금지어·Citation·무료 품질 규칙으로 결과를 채점한다."""
    errors: list[str] = []
    combined = f"{generated.title} {generated.summary} {generated.body}".casefold()
    required = [str(value).casefold() for value in expected.get("required_any", [])]
    if required and not any(value in combined for value in required):
        errors.append("핵심어 누락")
    for phrase in expected.get("forbidden", []):
        if str(phrase).casefold() in combined:
            errors.append(f"금지 표현: {phrase}")
    if len(generated.body) < int(expected.get("min_body_chars", 0)):
        errors.append(f"본문 길이: {len(generated.body)}")
    citation_count = len(generated.citation_references)
    if citation_count < int(expected.get("min_citations", 0)):
        errors.append(f"Citation 수: {citation_count}")
    verdict = quality.evaluate_report(generated, context_count=context_count)
    if verdict.should_regenerate:
        errors.append(f"무료 품질 규칙: {verdict.reason}")
    return errors


def _revision() -> str:
    """현재 Commit과 공유 Prompt·Batch 구현 Hash로 실행 버전을 만든다."""
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    digest = hashlib.sha256()
    for path in (
        PROJECT_ROOT / "agent/prompts/templates/report_builder_system.md",
        PROJECT_ROOT / "agent/report_builder/features/generation.py",
        PROJECT_ROOT / "agent/report_builder/features/batch.py",
    ):
        digest.update(path.read_bytes())
    return f"{commit}+{digest.hexdigest()[:12]}"


def main() -> int:
    """전체 케이스를 실행해 결과를 기록하거나 예상량만 출력한다."""
    args = _args()
    cases = _load_cases()
    estimated_input, estimated_output = _estimate_tokens(cases, args.model)
    if args.estimate_only:
        print(
            json.dumps(
                {
                    "case_count": len(cases),
                    "api_call_count": len(cases),
                    "estimated_input_tokens_upper": estimated_input,
                    "estimated_output_tokens_upper": estimated_output,
                },
                ensure_ascii=False,
            )
        )
        return 0

    usage = Usage()
    rows: list[dict[str, Any]] = []
    for case in cases:
        prompt = _prompt(case, args.model)
        started = time.perf_counter()
        before_input = usage.input_tokens
        before_output = usage.output_tokens
        try:
            completion = complete_with_usage(
                prompt.system_prompt,
                prompt.user_prompt,
                model=args.model,
                temperature=0.3,
            )
            usage.input_tokens += completion.input_tokens
            usage.output_tokens += completion.output_tokens
            generated = parse_report_generation(
                completion.text,
                allowed_references=prompt.allowed_references,
            )
            errors = _score(generated, case["expected"], len(case["contexts"]))
        except Exception as error:  # noqa: BLE001 - 실패도 결과에 그대로 기록한다
            errors = [f"{type(error).__name__}: {error}"]
        rows.append(
            {
                "id": case["id"],
                "passed": not errors,
                "errors": errors,
                "latency": time.perf_counter() - started,
                "input_tokens": usage.input_tokens - before_input,
                "output_tokens": usage.output_tokens - before_output,
            }
        )

    now = datetime.now(UTC)
    passed_count = sum(int(row["passed"]) for row in rows)
    total_latency = sum(float(row["latency"]) for row in rows)
    cost = (
        usage.input_tokens * args.input_cost_per_million
        + usage.output_tokens * args.output_cost_per_million
    ) / 1_000_000
    result_dir = ROOT / "results"
    result_dir.mkdir(exist_ok=True)
    result_path = result_dir / f"{now.date().isoformat()}_{args.model}.md"
    lines = [
        "# Report Batch Generation Benchmark",
        "",
        f"- 실행 날짜: {now.isoformat()}",
        f"- 모델: {args.model}",
        f"- Prompt·구현 버전: {_revision()}",
        f"- 케이스: {len(rows)} / 성공: {passed_count}",
        f"- 정확도: {passed_count / len(rows):.2%}",
        f"- 평균 지연시간: {total_latency / len(rows):.3f}s",
        f"- 입력 토큰: {usage.input_tokens} / 출력 토큰: {usage.output_tokens}",
        f"- 예상 비용: ${cost:.6f}",
        "",
        "| ID | 결과 | 지연 | Input | Output | 실패 사유 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        reason = "; ".join(row["errors"]).replace("|", "\\|")
        lines.append(
            f"| {row['id']} | {'PASS' if row['passed'] else 'FAIL'} | "
            f"{row['latency']:.3f}s | {row['input_tokens']} | "
            f"{row['output_tokens']} | {reason} |"
        )
    result_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(result_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
