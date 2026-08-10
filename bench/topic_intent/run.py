"""토픽 신선도 판정(news/evergreen) 벤치마크 실행기.

실제 OpenAI API를 호출하며 케이스별 성공·실패, 지연시간, 토큰 사용량과
예상 비용을 results/에 기록한다.

실행:
    uv run python bench/topic_intent/run.py \\
        --input-cost-per-million 0.40 --output-cost-per-million 1.60
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

# OPENAI_API_KEY를 .env에서 읽는다(앱 진입점과 같은 방식).
load_dotenv(PROJECT_ROOT / ".env")

from agent.assistant.features import topic_intent
from agent.llm.api import complete_with_usage

ROOT = Path(__file__).resolve().parent


@dataclass(slots=True)
class Usage:
    """벤치마크 전체의 입력·출력 토큰을 누적한다."""

    input_tokens: int = 0
    output_tokens: int = 0


def _args() -> argparse.Namespace:
    """모델과 토큰 단가 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(description="Topic freshness intent benchmark")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--input-cost-per-million", type=float, required=True)
    parser.add_argument("--output-cost-per-million", type=float, required=True)
    return parser.parse_args()


def _load_cases() -> list[dict[str, str]]:
    """dataset.jsonl의 평가 케이스를 읽는다."""
    lines = (ROOT / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _prompt_version() -> str:
    """현재 커밋과 프롬프트 내용으로 재현 가능한 버전 표기를 만든다."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=PROJECT_ROOT,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 — git이 없어도 벤치는 돌아야 한다
        commit = "unknown"
    import hashlib

    digest = hashlib.sha256(topic_intent._SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]
    return f"{commit}+{digest}"


def main() -> int:
    """모든 케이스를 판정하고 결과를 results/에 기록한다."""
    args = _args()
    cases = _load_cases()
    usage = Usage()
    rows: list[tuple[str, str, str, bool, float]] = []
    latencies: list[float] = []

    for case in cases:
        topic = case["topic"]
        started = time.monotonic()
        completion = complete_with_usage(
            topic_intent._SYSTEM_PROMPT, f"주제: {topic}", model=args.model
        )
        elapsed = time.monotonic() - started
        latencies.append(elapsed)
        usage.input_tokens += completion.input_tokens
        usage.output_tokens += completion.output_tokens
        answer = completion.text.strip().strip("`\"' .").lower()
        # 서비스 코드와 같은 규칙: 모르는 응답은 news로 떨어진다.
        actual = "evergreen" if answer == "evergreen" else "news"
        rows.append((topic, case["expected"], actual, actual == case["expected"], elapsed))

    passed = sum(1 for _, _, _, ok, _ in rows if ok)
    cost = (
        usage.input_tokens * args.input_cost_per_million
        + usage.output_tokens * args.output_cost_per_million
    ) / 1_000_000

    lines = [
        "# 토픽 신선도 판정 벤치마크",
        "",
        f"- 실행 날짜: {datetime.now(UTC).isoformat()}",
        f"- 모델: {args.model}",
        f"- 프롬프트 버전: {_prompt_version()}",
        f"- 케이스: {len(rows)}",
        f"- 성공: {passed}",
        f"- 정확도: {100.0 * passed / len(rows):.2f}%",
        f"- 평균 지연시간: {sum(latencies) / len(latencies):.3f}s",
        f"- 입력 토큰: {usage.input_tokens} / 출력 토큰: {usage.output_tokens}",
        f"- 예상 비용: ${cost:.6f}",
        "",
        "## 케이스별 결과",
        "",
        "| 주제 | 기대 | 실제 | 결과 | 지연 |",
        "|---|---|---|---|---:|",
    ]
    for topic, expected, actual, ok, elapsed in rows:
        lines.append(
            f"| {topic} | {expected} | {actual} | {'PASS' if ok else 'FAIL'} | {elapsed:.2f}s |"
        )

    results = ROOT / "results"
    results.mkdir(exist_ok=True)
    out = results / f"{datetime.now(UTC):%Y-%m-%d}_{args.model}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
