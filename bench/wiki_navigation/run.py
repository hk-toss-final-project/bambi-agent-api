"""Report Builder Reader의 Wiki 후보 선택 Tool Loop 벤치마크 실행기.

실제 OpenAI API로 SYSTEM_PROMPT와 Tool Calling을 실행하고 후보 Recall@30,
선택 Page Precision, Global 검색 판단, 지연·Token·비용을 기록한다.
"""

from __future__ import annotations

import argparse
import asyncio
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

load_dotenv(PROJECT_ROOT / ".env")

from agent.llm.api import ToolSpec, run_tool_loop
from agent.report_builder.features.researcher import SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parent
MAX_ITERATIONS = 5


@dataclass(slots=True)
class Usage:
    """전체 Tool Loop의 입력·출력 Token을 누적한다."""

    input_tokens: int = 0
    output_tokens: int = 0


def _args() -> argparse.Namespace:
    """모델·단가와 무료 추정 모드 인자를 파싱한다."""
    parser = argparse.ArgumentParser(description="Wiki Navigator Reader benchmark")
    parser.add_argument("--model", default="gpt-4.1-mini")
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
    """JSONL 평가 케이스를 순서대로 읽는다."""
    return [
        json.loads(line)
        for line in (ROOT / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _expanded_candidates(case: dict[str, Any]) -> list[dict[str, str]]:
    """rank 30 경계 케이스에 무관한 채움 후보를 추가하고 목표를 끝으로 옮긴다."""
    candidates = [dict(candidate) for candidate in case["candidates"]]
    target_id = str(case.get("move_last") or "")
    target = next(
        (candidate for candidate in candidates if candidate["id"] == target_id), None
    )
    if target is not None:
        candidates.remove(target)
    pad_to = int(case.get("pad_to") or len(candidates) + int(target is not None))
    filler_count = max(0, pad_to - len(candidates) - int(target is not None))
    candidates.extend(
        {
            "id": f"filler-{index}",
            "title": f"무관 후보 {index}",
            "summary": "질문과 관계없는 일반 도구 메모",
        }
        for index in range(1, filler_count + 1)
    )
    if target is not None:
        candidates.append(target)
    return candidates


def _candidate_observation(candidates: list[dict[str, str]]) -> str:
    """실제 wiki_search와 같은 ID·제목·요약 후보 관찰을 만든다."""
    lines = [f"Wiki 후보 {len(candidates)}개. 읽을 후보의 document_version_id를 고른다."]
    lines.extend(
        f"{index}. [{candidate['id']}] {candidate['title']} "
        f"(keyword={index}) — {candidate['summary']}"
        for index, candidate in enumerate(candidates, start=1)
    )
    return "\n".join(lines)


def _tools(case: dict[str, Any]) -> list[ToolSpec]:
    """케이스의 후보와 Global 자료를 반환하는 무상 Tool Double을 만든다."""
    candidates = _expanded_candidates(case)

    async def wiki_search(query: str) -> str:
        """질의와 관계없이 케이스의 Logical Index 후보를 반환한다."""
        return _candidate_observation(candidates)

    async def wiki_read(document_version_ids: list[str]) -> str:
        """선택 Page와 Source 저장 시각이 있는 읽기 결과를 반환한다."""
        allowed = {candidate["id"]: candidate for candidate in candidates}
        selected = [
            allowed[version_id]
            for version_id in document_version_ids
            if version_id in allowed
        ]
        if not selected:
            return "읽은 Wiki Page 없음."
        return "\n".join(
            f"{item['title']}: {item['summary']} "
            "(saved_at=2026-08-10T09:30:00+00:00)"
            for item in selected
        )

    async def search_pool(query: str) -> str:
        """케이스에 지정한 Global 저장 자료를 반환한다."""
        return str(case.get("pool") or "결과 없음")

    return [
        ToolSpec(
            name="wiki_search",
            description="개인 Wiki 후보를 최대 30개 찾는다. 이후 wiki_read가 필요하다.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            run=wiki_search,
        ),
        ToolSpec(
            name="wiki_read",
            description="후보 중 필요한 Page Version을 최대 6개 읽는다.",
            parameters={
                "type": "object",
                "properties": {
                    "document_version_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 6,
                    }
                },
                "required": ["document_version_ids"],
            },
            run=wiki_read,
        ),
        ToolSpec(
            name="search_pool",
            description="최신 외부 사실이 필요할 때 Global 저장 자료를 찾는다.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            run=search_pool,
        ),
    ]


def _estimate_tokens(cases: list[dict[str, Any]]) -> tuple[int, int, int]:
    """최대 Tool 왕복 수를 기준으로 보수적인 Token·API 호출 상한을 계산한다."""
    input_chars = 0
    for case in cases:
        observation = _candidate_observation(_expanded_candidates(case))
        input_chars += MAX_ITERATIONS * (
            len(SYSTEM_PROMPT) + len(case["topic"]) + len(observation) + 500
        )
    return input_chars // 2 + 1, len(cases) * MAX_ITERATIONS * 200, (
        len(cases) * MAX_ITERATIONS
    )


def _revision() -> str:
    """현재 Commit과 Reader Prompt·도구 코드 Hash를 결합한다."""
    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    digest = hashlib.sha256()
    for path in (
        PROJECT_ROOT / "agent/report_builder/features/researcher.py",
        ROOT / "dataset.jsonl",
    ):
        digest.update(path.read_bytes())
    return f"{completed.stdout.strip()}+{digest.hexdigest()[:12]}"


def _score(case: dict[str, Any], calls: tuple[Any, ...]) -> dict[str, object]:
    """Tool Trace로 후보 회수·Page 선택·Global 검색 판단을 채점한다."""
    expected = case["expected"]
    read_calls = [call for call in calls if call.name == "wiki_read" and not call.failed]
    selected = {
        str(version_id)
        for call in read_calls
        for version_id in call.arguments.get("document_version_ids", [])
    }
    required_any = set(expected.get("seed_any", []))
    required_all = set(expected.get("seed_all", []))
    forbidden = set(expected.get("forbidden", []))
    correct = required_any | required_all
    selection_ok = (
        not required_any or bool(selected & required_any)
    ) and required_all.issubset(selected)
    selection_ok = selection_ok and not bool(selected & forbidden)
    if not correct:
        selection_ok = selection_ok and not selected
    precision = len(selected & correct) / len(selected) if selected else float(not correct)
    actual_pool = any(call.name == "search_pool" and not call.failed for call in calls)
    return {
        "selected": sorted(selected),
        "selection_ok": selection_ok,
        "precision": precision,
        "pool_ok": actual_pool is bool(expected.get("search_pool")),
        "wiki_search_called": any(call.name == "wiki_search" for call in calls),
    }


async def _run(args: argparse.Namespace, cases: list[dict[str, Any]]) -> int:
    """모든 케이스의 실제 Tool Loop를 실행하고 Markdown 결과를 기록한다."""
    usage = Usage()
    rows: list[dict[str, object]] = []
    for case in cases:
        started = time.perf_counter()
        result = await run_tool_loop(
            SYSTEM_PROMPT,
            f"리포트 주제: {case['topic']}\n이 주제로 리포트를 쓸 근거 자료를 모아라.",
            _tools(case),
            model=args.model,
            max_iterations=MAX_ITERATIONS,
        )
        score = _score(case, result.calls)
        usage.input_tokens += result.input_tokens
        usage.output_tokens += result.output_tokens
        rows.append(
            {
                "id": case["id"],
                **score,
                "latency": time.perf_counter() - started,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            }
        )
    passed = sum(
        int(
            bool(row["selection_ok"])
            and bool(row["pool_ok"])
            and bool(row["wiki_search_called"])
        )
        for row in rows
    )
    average_precision = sum(float(row["precision"]) for row in rows) / len(rows)
    average_latency = sum(float(row["latency"]) for row in rows) / len(rows)
    cost = (
        usage.input_tokens * args.input_cost_per_million
        + usage.output_tokens * args.output_cost_per_million
    ) / 1_000_000
    now = datetime.now(UTC)
    result_dir = ROOT / "results"
    result_dir.mkdir(exist_ok=True)
    result_path = result_dir / f"{now.date().isoformat()}_{args.model.replace('/', '-')}.md"
    previous = sorted(path for path in result_dir.glob("*.md") if path != result_path)
    lines = [
        "# Wiki Navigator Reader Benchmark",
        "",
        f"- 실행 날짜: {now.isoformat()}",
        f"- 모델: {args.model}",
        f"- 프롬프트 버전: {_revision()}",
        f"- 케이스: {len(rows)} / 성공: {passed}",
        f"- Seed Recall@30: 100.00% (데이터셋 후보 계약)",
        f"- 선택 Page Precision: {average_precision:.2%}",
        f"- 전체 정확도: {passed / len(rows):.2%}",
        f"- 평균 지연시간: {average_latency:.3f}s",
        f"- 입력 Token: {usage.input_tokens} / 출력 Token: {usage.output_tokens}",
        f"- 비용: ${cost:.6f}",
        f"- 이전 결과 비교: {previous[-1].name if previous else '비교 대상 없음'}",
        "",
        "| ID | 결과 | 선택 | Precision | Pool | 지연 | Input | Output |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        ok = bool(row["selection_ok"]) and bool(row["pool_ok"])
        lines.append(
            f"| {row['id']} | {'PASS' if ok else 'FAIL'} | "
            f"{','.join(row['selected']) or '-'} | {float(row['precision']):.2%} | "
            f"{'PASS' if row['pool_ok'] else 'FAIL'} | {float(row['latency']):.2f}s | "
            f"{row['input_tokens']} | {row['output_tokens']} |"
        )
    result_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(result_path)
    return 0


def main() -> int:
    """무료 예상량을 출력하거나 승인된 실제 벤치마크를 실행한다."""
    args = _args()
    cases = _load_cases()
    if args.estimate_only:
        estimated_input, estimated_output, api_calls = _estimate_tokens(cases)
        print(
            json.dumps(
                {
                    "case_count": len(cases),
                    "api_call_count_upper": api_calls,
                    "estimated_input_tokens_upper": estimated_input,
                    "estimated_output_tokens_upper": estimated_output,
                },
                ensure_ascii=False,
            )
        )
        return 0
    return asyncio.run(_run(args, cases))


if __name__ == "__main__":
    raise SystemExit(main())
