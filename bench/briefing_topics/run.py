"""아침 브리핑 주제 선정 품질 벤치마크 실행기.

실제 OpenAI API를 호출하며 케이스별 성공·실패, 지연시간, 토큰 사용량과
예상 비용을 results/에 기록한다.

채점 기준은 "정답 3개를 맞혔나"가 아니다. 어떤 셋을 고를지는 취향이 갈리는
문제라 정답이 하나가 아니고, 실제로 중요한 것은 **파편이 안 뽑히는가**다.
아침 브리핑은 사용자가 검토하지 않고 받는 경로라, 도구·출처가 주제로 나가면
그대로 발행된다.

실행:
    uv run python bench/briefing_topics/run.py --estimate-only
    uv run python bench/briefing_topics/run.py \\
        --input-cost-per-million 0.40 --output-cost-per-million 1.60
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

from agent.llm.api import complete_with_usage
from agent.report_builder.features import briefing_topics
from agent.report_builder.features.briefing_topics import (
    InterestCandidate,
    InterestContext,
)

ROOT = Path(__file__).resolve().parent


@dataclass(slots=True)
class Usage:
    """벤치마크 전체의 입력·출력 토큰을 누적한다."""

    input_tokens: int = 0
    output_tokens: int = 0


def _args() -> argparse.Namespace:
    """모델과 토큰 단가 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(description="Briefing topic selection benchmark")
    parser.add_argument("--model", default="gpt-4.1-mini")
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
    """dataset.jsonl의 평가 케이스를 읽는다."""
    lines = (ROOT / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _billable_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """실제로 모델을 부르는 케이스만 남긴다.

    후보가 고를 개수 이하면 서비스 코드가 호출을 건너뛰므로 비용도 들지 않는다.
    """
    return [
        case
        for case in cases
        if len(case["candidates"]) > case["expected"].get("limit", 3)
    ]


def _estimate_tokens(cases: list[dict[str, Any]]) -> tuple[int, int]:
    """실행 승인 전에 볼 보수적인 입력·출력 Token 상한을 계산한다."""
    input_chars = 0
    for case in _billable_cases(cases):
        candidate_chars = sum(
            len(item["node"]) + len(item.get("context", "")) + 8
            for item in case["candidates"]
        )
        input_chars += (
            len(briefing_topics._SYSTEM_PROMPT)
            + candidate_chars
            + len(case.get("user_summary", ""))
            + 100
        )
    # 한국어는 글자당 Token 비율이 높을 수 있어 입력은 2글자/Token,
    # 주제 3개 + 사유 한 문장인 출력은 케이스당 최대 200 Token으로 잡는다.
    return (input_chars // 2 + 1, len(_billable_cases(cases)) * 200)


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
    digest = hashlib.sha256(
        briefing_topics._SYSTEM_PROMPT.encode("utf-8")
    ).hexdigest()[:12]
    return f"{commit}+{digest}"


def _score(topics: list[str], expected: dict[str, Any]) -> list[str]:
    """선정 결과를 케이스 기대값으로 채점하고 실패 사유를 모은다."""
    errors: list[str] = []
    chosen = set(topics)

    # 파편이 뽑히는 것이 가장 나쁜 실패다 — 검토 없이 발행된다.
    for node in expected.get("forbidden", []):
        if node in chosen:
            errors.append(f"파편 선택: {node}")

    # 진짜 관심사가 하나도 안 들어가면 브리핑이 무의미해진다.
    required_any = expected.get("required_any", [])
    if required_any and not (chosen & set(required_any)):
        errors.append(f"진짜 관심사 누락: {'/'.join(required_any)} 중 0개")

    count = expected.get("required_count")
    if count is not None and len(topics) != count:
        errors.append(f"개수: {len(topics)}개 (기대 {count})")

    limit = expected.get("limit")
    if limit is not None and len(topics) > limit:
        errors.append(f"상한 초과: {len(topics)}개 > {limit}")

    # 같은 대상을 가리키는 후보가 여럿일 때 하나만 골라야 한다.
    pair = expected.get("at_most_one_of", [])
    if pair and len(chosen & set(pair)) > 1:
        errors.append(f"중복 대상: {'/'.join(sorted(chosen & set(pair)))}")

    # 세 자리를 같은 사안으로 채우면 브리핑이 한 얘기만 하게 된다.
    group_rule = expected.get("max_from_group")
    if group_rule:
        picked = chosen & set(group_rule["group"])
        if len(picked) > group_rule["max"]:
            errors.append(
                f"한 사안 편중: {len(picked)}개 > {group_rule['max']} ({'/'.join(sorted(picked))})"
            )
    return errors


def main() -> int:
    """모든 케이스를 선정하고 결과를 results/에 기록한다."""
    args = _args()
    cases = _load_cases()
    if args.estimate_only:
        estimated_input, estimated_output = _estimate_tokens(cases)
        print(
            json.dumps(
                {
                    "case_count": len(cases),
                    "api_call_count": len(_billable_cases(cases)),
                    "estimated_input_tokens_upper": estimated_input,
                    "estimated_output_tokens_upper": estimated_output,
                },
                ensure_ascii=False,
            )
        )
        return 0

    usage = Usage()
    rows: list[tuple[str, list[str], list[str], float]] = []

    for case in cases:
        context = InterestContext(
            candidates=[
                InterestCandidate(node=item["node"], context=item.get("context", ""))
                for item in case["candidates"]
            ],
            user_summary=case.get("user_summary", ""),
        )
        expected = case["expected"]
        limit = expected.get("limit", 3)
        started = time.monotonic()

        # 후보가 상한 이하면 서비스 코드가 모델을 부르지 않는다. 그 경로도 그대로 잰다.
        if len(context.candidates) <= limit:
            topics = [candidate.node for candidate in context.candidates]
        else:
            prompt = briefing_topics._build_user_prompt(context, limit=limit)
            completion = complete_with_usage(
                briefing_topics._SYSTEM_PROMPT, prompt, model=args.model
            )
            usage.input_tokens += completion.input_tokens
            usage.output_tokens += completion.output_tokens
            try:
                selection = briefing_topics._parse_selection(
                    completion.text,
                    allowed=[c.node for c in context.candidates],
                    limit=limit,
                )
                topics = list(selection.topics)
            except Exception as error:  # noqa: BLE001 — 파싱 실패도 결과로 남긴다
                rows.append((case["id"], [], [f"파싱 실패: {error}"], time.monotonic() - started))
                continue

        rows.append((case["id"], topics, _score(topics, expected), time.monotonic() - started))

    passed = sum(1 for _, _, errors, _ in rows if not errors)
    fragment_failures = sum(
        1 for _, _, errors, _ in rows if any(e.startswith("파편 선택") for e in errors)
    )
    cost = (
        usage.input_tokens * args.input_cost_per_million
        + usage.output_tokens * args.output_cost_per_million
    ) / 1_000_000
    latencies = [elapsed for _, _, _, elapsed in rows]

    lines = [
        "# 아침 브리핑 주제 선정 벤치마크",
        "",
        f"- 실행 날짜: {datetime.now(UTC).isoformat()}",
        f"- 모델: {args.model}",
        f"- 프롬프트 버전: {_prompt_version()}",
        f"- 케이스: {len(rows)}",
        f"- 성공: {passed}",
        f"- 정확도: {100.0 * passed / len(rows):.2f}%",
        f"- **파편 선택 실패: {fragment_failures}건** (가장 나쁜 실패 — 검토 없이 발행된다)",
        f"- 평균 지연시간: {sum(latencies) / len(latencies):.3f}s",
        f"- 입력 토큰: {usage.input_tokens} / 출력 토큰: {usage.output_tokens}",
        f"- 예상 비용: ${cost:.6f}",
        "",
        "## 케이스별 결과",
        "",
        "| ID | 고른 주제 | 결과 | 실패 사유 | 지연 |",
        "|---|---|---|---|---:|",
    ]
    for case_id, topics, errors, elapsed in rows:
        lines.append(
            f"| {case_id} | {', '.join(topics) or '(없음)'} | "
            f"{'PASS' if not errors else 'FAIL'} | {'; '.join(errors)} | {elapsed:.2f}s |"
        )

    results = ROOT / "results"
    results.mkdir(exist_ok=True)
    out = results / f"{datetime.now(UTC):%Y-%m-%d}_{args.model}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
