"""Wiki canonical identity LLM 판정 품질 벤치마크 실행기.

entity·concept 충돌, 한영 혼용, 동음이의어와 프롬프트 주입 케이스를 실제
OpenAI 모델로 판정한다. 실행 전 예상 토큰·비용을 표시하고 --confirm-cost가
있을 때만 호출하며, 전 케이스 결과와 지연시간·토큰·비용을 Markdown으로 남긴다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from agent.wiki_builder.api import (
    prepare_wiki_identity_resolution,
    resolve_wiki_identity_conflicts,
)
from shared.wiki_models import (
    ConceptClassification,
    EntityClassification,
    ExistingWikiEntry,
    WikiClassification,
)

ROOT = Path(__file__).resolve().parent
ESTIMATED_INPUT_TOKENS_PER_CASE = 2_500
ESTIMATED_OUTPUT_TOKENS_PER_CASE = 200


def _args() -> argparse.Namespace:
    """모델·토큰 단가와 비용 승인 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(description="Wiki identity resolution benchmark")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--input-cost-per-million", type=float, required=True)
    parser.add_argument("--output-cost-per-million", type=float, required=True)
    parser.add_argument("--confirm-cost", action="store_true")
    return parser.parse_args()


def _load_cases() -> list[dict[str, Any]]:
    """JSONL 데이터셋의 모든 비어 있지 않은 줄을 읽는다."""
    return [
        json.loads(line)
        for line in (ROOT / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _classification(payload: dict[str, Any]) -> WikiClassification:
    """데이터셋 JSON을 Wiki 분류 값 객체로 변환한다."""
    return WikiClassification(
        source_summary=str(payload.get("source_summary") or ""),
        entities=[EntityClassification(**item) for item in payload.get("entities", [])],
        concepts=[ConceptClassification(**item) for item in payload.get("concepts", [])],
    )


def _entries(items: list[dict[str, Any]]) -> list[ExistingWikiEntry]:
    """데이터셋의 기존 Wiki 문서 목록을 값 객체로 변환한다."""
    return [ExistingWikiEntry(**item) for item in items]


def _score(
    classification: WikiClassification, expected: dict[str, Any]
) -> tuple[bool, list[str]]:
    """canonical kind·key·제목과 최종 노드 수를 기대값과 비교한다."""
    errors: list[str] = []
    nodes: list[tuple[str, object]] = [
        *(('entity', entity) for entity in classification.entities),
        *(('concept', concept) for concept in classification.concepts),
    ]
    expected_count = int(expected.get("node_count", 1))
    if len(nodes) != expected_count:
        errors.append(f"node count: {len(nodes)} != {expected_count}")
    kind = str(expected["document_kind"])
    candidates = [value for node_kind, value in nodes if node_kind == kind]
    if not candidates:
        errors.append(f"missing kind: {kind}")
        return False, errors
    expected_key = expected.get("document_key")
    expected_title = str(expected.get("title") or "").casefold()
    if not any(
        getattr(candidate, "matched_existing_key", None) == expected_key
        and (
            not expected_title
            or str(
                getattr(candidate, "name", "") or getattr(candidate, "title", "")
            ).casefold()
            == expected_title
        )
        for candidate in candidates
    ):
        errors.append(
            f"canonical mismatch: kind={kind}, key={expected_key}, title={expected_title}"
        )
    return not errors, errors


def _git_revision() -> str:
    """결과 재현용 현재 Git revision을 반환한다."""
    return subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        text=True,
    ).strip()


def main() -> None:
    """비용 승인 후 모든 케이스를 실행하고 결과 파일을 작성한다."""
    args = _args()
    cases = _load_cases()
    estimated_input = len(cases) * ESTIMATED_INPUT_TOKENS_PER_CASE
    estimated_output = len(cases) * ESTIMATED_OUTPUT_TOKENS_PER_CASE
    estimated_cost = (
        estimated_input * args.input_cost_per_million
        + estimated_output * args.output_cost_per_million
    ) / 1_000_000
    print(
        f"cases={len(cases)}, estimated_tokens={estimated_input}+{estimated_output}, "
        f"estimated_cost=${estimated_cost:.6f}"
    )
    if not args.confirm_cost:
        raise SystemExit("실제 호출하려면 예상 비용을 확인한 뒤 --confirm-cost를 추가하세요.")

    rows: list[dict[str, Any]] = []
    total_input = 0
    total_output = 0
    for case in cases:
        started = time.perf_counter()
        try:
            classification = _classification(case["classification"])
            draft = prepare_wiki_identity_resolution(
                classification=classification,
                existing_entities=_entries(case.get("existing_entities", [])),
                existing_concepts=_entries(case.get("existing_concepts", [])),
            )
            result = resolve_wiki_identity_conflicts(
                draft=draft,
                source_title=str(case["source_title"]),
                model=args.model,
            )
            passed, errors = _score(result.classification, case["expected"])
            total_input += result.input_tokens
            total_output += result.output_tokens
        except Exception as error:  # noqa: BLE001 - 실패도 결과에 반드시 기록한다.
            passed, errors = False, [f"{type(error).__name__}: {error}"]
            result = None
        rows.append(
            {
                "id": case["id"],
                "passed": passed,
                "errors": errors,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "input_tokens": result.input_tokens if result else 0,
                "output_tokens": result.output_tokens if result else 0,
            }
        )

    actual_cost = (
        total_input * args.input_cost_per_million
        + total_output * args.output_cost_per_million
    ) / 1_000_000
    passed_count = sum(1 for row in rows if row["passed"])
    average_latency = sum(row["latency_ms"] for row in rows) / len(rows)
    now = datetime.now(UTC)
    lines = [
        "# Wiki identity resolution benchmark",
        "",
        f"- 실행 날짜: {now.isoformat()}",
        f"- 모델: {args.model}",
        f"- 프롬프트 버전: {_git_revision()}",
        f"- 정확도: {passed_count}/{len(rows)} ({passed_count / len(rows):.1%})",
        f"- 평균 지연시간: {average_latency:.0f}ms",
        f"- 토큰: input {total_input}, output {total_output}",
        f"- 예상 비용: ${actual_cost:.6f}",
        "- 이전 결과 비교: 최초 기준선 실행",
        "",
        "| case | result | latency | tokens | errors |",
        "|---|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['id']} | {'PASS' if row['passed'] else 'FAIL'} | "
            f"{row['latency_ms']}ms | {row['input_tokens']}+{row['output_tokens']} | "
            f"{'<br>'.join(row['errors']) or '-'} |"
        )
    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    model_slug = args.model.replace("/", "-")
    output = results_dir / f"{now.date().isoformat()}_{model_slug}.md"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
