"""사용자 추가 Topic의 일반론 컨텍스트 생성 품질 벤치마크 실행기.

실제 OpenAI API를 호출하고 케이스별 구조·안전·모호성 기준, 지연시간,
토큰 사용량과 전달받은 단가 기준 비용을 Markdown 결과로 남긴다.
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.llm.api import complete_with_usage
from agent.wiki_builder.features.onboarding_contexts import (
    CUSTOM_TOPIC_PROMPT_VERSION,
    resolve_onboarding_contexts,
)

ROOT = Path(__file__).resolve().parent


@dataclass(slots=True)
class Usage:
    """벤치마크 전체의 LLM 토큰 사용량을 누적한다."""

    input_tokens: int = 0
    output_tokens: int = 0


def _args() -> argparse.Namespace:
    """실행 모델·단가와 무료 추정 모드 인자를 파싱한다."""
    parser = argparse.ArgumentParser(description="Custom topic context benchmark")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--input-cost-per-million", type=float)
    parser.add_argument("--output-cost-per-million", type=float)
    parser.add_argument("--estimate-only", action="store_true")
    args = parser.parse_args()
    if not args.estimate_only and (
        args.input_cost_per_million is None
        or args.output_cost_per_million is None
    ):
        parser.error("실제 실행에는 입력·출력 백만 Token당 단가가 필요합니다.")
    return args


def _load_cases() -> list[dict[str, Any]]:
    """JSONL 데이터셋을 순서와 케이스 ID를 보존해 읽는다."""
    return [
        json.loads(line)
        for line in (ROOT / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _estimate_tokens(cases: list[dict[str, Any]]) -> tuple[int, int]:
    """실행 승인 전에 볼 보수적인 입력·출력 Token 상한을 계산한다."""
    prompt_chars = (
        PROJECT_ROOT
        / "agent/prompts/templates/custom_topic_context.md"
    ).read_text(encoding="utf-8")
    input_chars = sum(
        len(prompt_chars) + len(str(case["keyword"])) + 200 for case in cases
    )
    # 한국어는 글자당 Token 비율이 높을 수 있어 입력은 2글자/Token,
    # 구조화 JSON 출력은 케이스당 최대 400 Token으로 보수적으로 잡는다.
    return (input_chars // 2 + 1, len(cases) * 400)


def _score(context: object, expected: dict[str, Any]) -> tuple[bool, list[str]]:
    """구조·일반론·안전·모호성 기대값으로 컨텍스트 한 건을 채점한다."""
    errors: list[str] = []
    definition = str(getattr(context, "definition", ""))
    combined = " ".join(
        (
            str(getattr(context, "canonical_name", "")),
            definition,
            *getattr(context, "key_characteristics", ()),
            *getattr(context, "applications", ()),
        )
    ).casefold()
    if getattr(context, "resolution_kind", None) != "llm_generated":
        errors.append(
            f"resolution_kind={getattr(context, 'resolution_kind', None)}"
        )
    expected_kind = expected.get("node_kind")
    if expected_kind and getattr(context, "node_kind", None) != expected_kind:
        errors.append(f"node_kind={getattr(context, 'node_kind', None)}")
    subtypes = expected.get("subtypes", [])
    if subtypes and getattr(context, "subtype", None) not in subtypes:
        errors.append(f"subtype={getattr(context, 'subtype', None)}")
    minimum_chars = int(expected.get("min_definition_chars", 20))
    if len(definition) < minimum_chars:
        errors.append(f"definition too short={len(definition)}")
    required_any = [str(item).casefold() for item in expected.get("definition_any", [])]
    if required_any and not any(term in combined for term in required_any):
        errors.append("definition missing expected term")
    for phrase in expected.get("forbidden", []):
        if str(phrase).casefold() in combined:
            errors.append(f"forbidden phrase={phrase}")
    possible_meanings = getattr(context, "possible_meanings", ())
    if len(possible_meanings) < int(expected.get("min_possible_meanings", 0)):
        errors.append(f"possible_meanings={len(possible_meanings)}")
    search_terms = getattr(context, "search_terms", ())
    if len(search_terms) < int(expected.get("min_search_terms", 0)):
        errors.append(f"search_terms={len(search_terms)}")
    return not errors, errors


def _revision() -> str:
    """현재 Commit과 해석 코드·Prompt Hash를 결합한 실행 버전을 만든다."""
    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    digest = hashlib.sha256()
    for path in (
        PROJECT_ROOT / "agent/wiki_builder/features/onboarding_contexts.py",
        PROJECT_ROOT / "agent/prompts/templates/custom_topic_context.md",
    ):
        digest.update(path.read_bytes())
    return f"{completed.stdout.strip()}+{digest.hexdigest()[:12]}"


def main() -> None:
    """데이터셋 전체를 실행하거나, API 호출 없이 예상량만 출력한다."""
    args = _args()
    cases = _load_cases()
    estimated_input, estimated_output = _estimate_tokens(cases)
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
        return

    usage = Usage()
    rows: list[dict[str, Any]] = []
    for case in cases:
        started = time.perf_counter()
        before_input = usage.input_tokens
        before_output = usage.output_tokens

        def tracked_complete(system: str, user: str, *, model: str) -> str:
            """공유 LLM 경계로 호출하고 현재 케이스 Token을 누적한다."""
            completion = complete_with_usage(
                system,
                user,
                model=model,
                temperature=0,
            )
            usage.input_tokens += completion.input_tokens
            usage.output_tokens += completion.output_tokens
            return completion.text

        try:
            resolution = resolve_onboarding_contexts(
                selected_topic_ids=[],
                custom_keywords=[str(case["keyword"])],
                taxonomy_version="1.0.0-draft",
                locale=str(case.get("locale") or "ko"),
                taxonomy_contexts=[],
                cached_contexts=[],
                existing_entries=[],
                model=args.model,
                generator=tracked_complete,
            )
            passed, errors = _score(resolution.contexts[0], case["expected"])
        except Exception as error:  # noqa: BLE001 - 실패도 결과에 그대로 기록한다.
            passed = False
            errors = [f"{type(error).__name__}: {error}"]
        rows.append(
            {
                "id": case["id"],
                "passed": passed,
                "errors": errors,
                "latency": time.perf_counter() - started,
                "input_tokens": usage.input_tokens - before_input,
                "output_tokens": usage.output_tokens - before_output,
            }
        )

    now = datetime.now(UTC)
    passed_count = sum(int(row["passed"]) for row in rows)
    total_latency = sum(float(row["latency"]) for row in rows)
    input_cost = usage.input_tokens * args.input_cost_per_million / 1_000_000
    output_cost = usage.output_tokens * args.output_cost_per_million / 1_000_000
    result_dir = ROOT / "results"
    result_dir.mkdir(exist_ok=True)
    result_path = result_dir / (
        f"{now.date().isoformat()}_{args.model.replace('/', '-')}.md"
    )
    previous = sorted(
        path for path in result_dir.glob("*.md") if path != result_path
    )
    lines = [
        "# Custom Topic Context Benchmark",
        "",
        f"- 실행 날짜: {now.isoformat()}",
        f"- 모델: {args.model}",
        f"- 프롬프트 버전: {CUSTOM_TOPIC_PROMPT_VERSION} ({_revision()})",
        f"- 케이스: {len(rows)}",
        f"- 성공: {passed_count}",
        f"- 정확도: {passed_count / len(rows):.2%}",
        f"- 평균 지연시간: {total_latency / len(rows):.3f}s",
        f"- 입력 토큰: {usage.input_tokens}",
        f"- 출력 토큰: {usage.output_tokens}",
        f"- 예상 비용: ${input_cost + output_cost:.6f}",
        f"- 이전 결과 비교: {previous[-1].name if previous else '비교 대상 없음'}",
        "",
        "## 케이스별 결과",
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


if __name__ == "__main__":
    main()
