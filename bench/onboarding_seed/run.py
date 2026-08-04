"""온보딩 관심사 씨앗의 Wiki 노드 생성 품질 벤치마크 실행기.

WSE-014가 합성한 씨앗 Markdown을 실제 Wiki 분류기(classify_source_for_wiki)에
태워, 온보딩에서 고른 관심 주제가 Entity·Concept 노드로 추출되는지 채점한다.
씨앗이 관심사 프로필(INT-011)로 파생되려면 이 노드 생성이 전제이기 때문이다.

실제 OpenAI API를 호출하며 케이스별 성공·실패, 지연시간, 토큰 사용량, 사용자가
전달한 백만 토큰당 단가 기준 예상 비용을 results/에 기록한다. 결과를 선별하지
않고 전 케이스를 기록한다.
"""

from __future__ import annotations

import argparse
import asyncio
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

from agent.llm.api import complete_with_usage
from agent.wiki_builder.features import classification
from domain.personal_wiki.source_events.api import wse_014

ROOT = Path(__file__).resolve().parent


@dataclass(slots=True)
class Usage:
    """벤치마크 전체의 입력·출력 토큰을 누적한다."""

    input_tokens: int = 0
    output_tokens: int = 0


def _args() -> argparse.Namespace:
    """모델과 토큰 단가 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(description="Onboarding seed LLM benchmark")
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


def _score(result: object, expected: dict[str, Any]) -> tuple[bool, list[str]]:
    """씨앗에서 나온 노드가 관심 주제를 담았는지 채점한다."""
    errors: list[str] = []
    names = {
        str(getattr(item, "name", "") or getattr(item, "title", "")).casefold()
        for item in [*result.entities, *result.concepts]
    }
    node_count = len(result.entities) + len(result.concepts)
    minimum = int(expected.get("min_nodes", 1))
    if node_count < minimum:
        errors.append(f"too few nodes: {node_count} < {minimum}")
    # 관심 라벨 중 최소 하나가 노드 이름(부분 일치)으로 등장해야 한다.
    wanted = expected.get("entities_any", [])
    if wanted and not any(
        any(label.casefold() in name for name in names) for label in wanted
    ):
        errors.append(f"no interest label surfaced as node: {wanted}")
    return not errors, errors


def main() -> None:
    """전체 케이스를 실행하고 선별 없이 Markdown 결과 파일을 작성한다."""
    args = _args()
    usage = Usage()

    def tracked_complete(system_prompt: str, user_prompt: str, model: str) -> str:
        """공유 LLM 경계로 호출하고 반환된 토큰 사용량을 누적한다."""
        completion = complete_with_usage(
            system_prompt,
            user_prompt,
            model=args.model,
            temperature=0,
        )
        usage.input_tokens += completion.input_tokens
        usage.output_tokens += completion.output_tokens
        return completion.text

    original_complete = classification.complete
    classification.complete = tracked_complete
    rows: list[dict[str, Any]] = []
    try:
        for case in _load_cases():
            started = time.perf_counter()
            before_input = usage.input_tokens
            before_output = usage.output_tokens
            try:
                payload = case["input"]
                seed = asyncio.run(
                    wse_014(
                        payload["signup_interests"],
                        interest_taxonomy_version=payload.get(
                            "interest_taxonomy_version"
                        ),
                    )
                )
                if seed is None:
                    raise ValueError("씨앗이 합성되지 않았습니다(빈 선택).")
                result = classification.classify_source_for_wiki(
                    source_title=seed.title,
                    source_content=seed.content,
                    source_description=None,
                    source_tags=[],
                    existing_entities=[],
                    existing_concepts=[],
                    model=args.model,
                )
                passed, errors = _score(result, case["expected"])
            except Exception as error:
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
    finally:
        classification.complete = original_complete

    now = datetime.now(UTC)
    passed_count = sum(int(row["passed"]) for row in rows)
    total_latency = sum(float(row["latency"]) for row in rows)
    input_cost = usage.input_tokens * args.input_cost_per_million / 1_000_000
    output_cost = usage.output_tokens * args.output_cost_per_million / 1_000_000
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    result_dir = ROOT / "results"
    result_dir.mkdir(exist_ok=True)
    safe_model = args.model.replace("/", "-")
    result_path = result_dir / f"{now.date().isoformat()}_{safe_model}.md"
    previous = sorted(path for path in result_dir.glob("*.md") if path != result_path)
    lines = [
        "# Onboarding Seed Benchmark",
        "",
        f"- 실행 날짜: {now.isoformat()}",
        f"- 모델: {args.model}",
        f"- 커밋: {commit}",
        f"- 케이스: {len(rows)}",
        f"- 성공: {passed_count}",
        f"- 정확도(케이스 전체 통과): {passed_count / len(rows):.2%}",
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
