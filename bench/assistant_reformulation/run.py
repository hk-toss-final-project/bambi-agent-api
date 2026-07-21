"""키워드 비서 검색어 재구성 프롬프트 품질 벤치마크 실행기.

리서치 에이전트(agent/assistant/features/graph.py)가 결과가 빈약할 때 호출하는
검색어 재구성 프롬프트를 실제 OpenAI API로 평가한다. 그래프와 같은 프롬프트를
쓰기 위해 graph.REFORMULATE_SYSTEM / build_reformulate_prompt를 그대로 import한다.

채점 기준(모두 결정론적 규칙 — LLM 심판을 쓰지 않는다):
    1. 비어 있지 않고 한 줄이어야 한다.
    2. 이미 시도한 검색어와 같으면 안 된다(같으면 그래프가 재시도를 포기한다).
    3. expected.max_chars 이내여야 한다(장문 설명을 뱉으면 검색어로 못 쓴다).
    4. expected.must_contain_any 중 최소 하나를 포함해야 한다(주제 이탈 방지).
    5. expected.forbidden에 있는 문자열과 같으면 안 된다.

실행:
    uv run python bench/assistant_reformulation/run.py \
        --input-cost-per-million 0.4 --output-cost-per-million 1.6
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

from dotenv import load_dotenv

# OPENAI_API_KEY를 .env에서 읽는다(앱 진입점과 같은 방식).
load_dotenv(PROJECT_ROOT / ".env")

from agent.assistant.features import graph
from agent.llm.api import complete_with_usage

ROOT = Path(__file__).resolve().parent


@dataclass(slots=True)
class Usage:
    """벤치마크 전체의 입력·출력 토큰을 누적한다."""

    input_tokens: int = 0
    output_tokens: int = 0


def _args() -> argparse.Namespace:
    """모델과 토큰 단가 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(description="Assistant query reformulation benchmark")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--input-cost-per-million", type=float, required=True)
    parser.add_argument("--output-cost-per-million", type=float, required=True)
    return parser.parse_args()


def _load_cases() -> list[dict[str, Any]]:
    """JSONL 데이터셋을 읽는다."""
    return [
        json.loads(line)
        for line in (ROOT / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _score(suggestion: str, payload: dict[str, Any], expected: dict[str, Any]) -> tuple[bool, list[str]]:
    """재구성 결과를 케이스 기준으로 채점한다."""
    errors: list[str] = []
    attempts = [str(item) for item in payload.get("attempts", [])]
    lowered = suggestion.casefold()

    if not suggestion:
        return False, ["empty suggestion"]
    if "\n" in suggestion:
        errors.append("multi-line suggestion")
    if any(suggestion.casefold() == attempt.casefold() for attempt in attempts):
        errors.append(f"repeats a tried query: {suggestion}")
    for forbidden in expected.get("forbidden", []):
        if suggestion.casefold() == str(forbidden).casefold():
            errors.append(f"forbidden query: {forbidden}")
    max_chars = int(expected.get("max_chars", 60))
    if len(suggestion) > max_chars:
        errors.append(f"too long: {len(suggestion)} > {max_chars}")
    anchors = [str(term) for term in expected.get("must_contain_any", [])]
    if anchors and not any(term.casefold() in lowered for term in anchors):
        errors.append(f"topic drift: none of {anchors} in '{suggestion}'")
    return not errors, errors


def _prompt_revision() -> str:
    """Git Commit과 그래프 코드 Hash를 결합한 Prompt 버전을 반환한다."""
    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    digest = hashlib.sha256()
    digest.update((PROJECT_ROOT / "agent/assistant/features/graph.py").read_bytes())
    return f"{completed.stdout.strip()}+{digest.hexdigest()[:12]}"


def main() -> None:
    """전체 케이스를 실행하고 선별 없이 Markdown 결과 파일을 작성한다."""
    args = _args()
    usage = Usage()
    rows: list[dict[str, Any]] = []

    for case in _load_cases():
        payload = case["input"]
        started = time.perf_counter()
        before_input, before_output = usage.input_tokens, usage.output_tokens
        try:
            completion = complete_with_usage(
                graph.REFORMULATE_SYSTEM,
                graph.build_reformulate_prompt(
                    str(payload["topic"]), [str(item) for item in payload.get("attempts", [])]
                ),
                model=args.model,
                temperature=0,
            )
            usage.input_tokens += completion.input_tokens
            usage.output_tokens += completion.output_tokens
            suggestion = graph.normalize_suggestion(completion.text)
            passed, errors = _score(suggestion, payload, case["expected"])
        except Exception as error:
            suggestion = ""
            passed = False
            errors = [f"{type(error).__name__}: {error}"]
        rows.append(
            {
                "id": case["id"],
                "topic": payload["topic"],
                "suggestion": suggestion,
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
    safe_model = args.model.replace("/", "-")
    revision = _prompt_revision()
    # 프롬프트를 고치고 같은 날 다시 돌리면 이전 결과를 덮어써 비교가 불가능해지므로,
    # 파일명에 Prompt 버전 해시를 넣어 버전별 결과를 모두 남긴다.
    result_path = result_dir / f"{now.date().isoformat()}_{safe_model}_{revision.split('+')[-1]}.md"

    lines = [
        "# Assistant Query Reformulation Benchmark",
        "",
        f"- 실행 날짜: {now.isoformat()}",
        f"- 모델: {args.model}",
        f"- Prompt 버전: {revision}",
        f"- 케이스 수: {len(rows)}",
        f"- 정확도: {passed_count}/{len(rows)} ({passed_count / len(rows):.1%})",
        f"- 평균 지연시간: {total_latency / len(rows):.2f}s",
        f"- 토큰: 입력 {usage.input_tokens} / 출력 {usage.output_tokens}",
        f"- 예상 비용: ${input_cost + output_cost:.4f}",
        "",
        "## 케이스별 결과",
        "",
        "| ID | 주제 | 제안된 검색어 | 결과 | 사유 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        status = "통과" if row["passed"] else "실패"
        reason = "; ".join(row["errors"]) or "-"
        lines.append(
            f"| {row['id']} | {row['topic']} | {row['suggestion'] or '-'} | {status} | {reason} |"
        )
    result_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"결과 기록: {result_path}")
    print(f"정확도: {passed_count}/{len(rows)}")


if __name__ == "__main__":
    main()
