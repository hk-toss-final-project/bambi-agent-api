"""개인 LLM Wiki 분류 품질 벤치마크 실행기.

실제 OpenAI API를 호출하며 케이스별 성공·실패, 지연시간, 토큰 사용량,
사용자가 전달한 백만 토큰당 단가 기준 예상 비용을 results/에 기록한다.
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

from langchain_openai import ChatOpenAI

from agent.wiki_builder.features import classification

ROOT = Path(__file__).resolve().parent


@dataclass(slots=True)
class Usage:
    """벤치마크 전체의 입력·출력 토큰을 누적한다."""

    input_tokens: int = 0
    output_tokens: int = 0


def _args() -> argparse.Namespace:
    """모델과 토큰 단가 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(description="Personal Wiki LLM benchmark")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--input-cost-per-million", type=float, required=True)
    parser.add_argument("--output-cost-per-million", type=float, required=True)
    return parser.parse_args()


def _load_cases() -> list[dict[str, Any]]:
    """JSONL 데이터셋을 읽고 repeat·suffix 필드로 긴 입력을 확장한다."""
    cases: list[dict[str, Any]] = []
    for line in (ROOT / "dataset.jsonl").read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        payload = case["input"]
        repeat = payload.pop("repeat", None)
        suffix = payload.pop("suffix", "")
        if repeat:
            payload["content"] += repeat["text"] * int(repeat["count"])
        payload["content"] += suffix
        cases.append(case)
    return cases


def _names(items: list[object], attribute: str) -> dict[str, object]:
    """분류 결과를 이름의 casefold 값으로 찾을 수 있는 Map으로 만든다."""
    return {str(getattr(item, attribute)).casefold(): item for item in items}


def _score(result: object, expected: dict[str, Any]) -> tuple[bool, list[str]]:
    """추출 결과를 케이스의 필수 이름·유형·별칭·인용 기준으로 채점한다."""
    errors: list[str] = []
    entities = _names(result.entities, "name")
    concepts = _names(result.concepts, "title")
    for name in expected.get("entities", []):
        if name.casefold() not in entities:
            errors.append(f"missing entity: {name}")
    for name in expected.get("concepts", []):
        if name.casefold() not in concepts:
            errors.append(f"missing concept: {name}")
    for name in expected.get("forbidden_entities", []):
        if name.casefold() in entities:
            errors.append(f"forbidden entity: {name}")
    if len(entities) > expected.get("max_entities", 10_000):
        errors.append(f"too many entities: {len(entities)}")
    if len(concepts) > expected.get("max_concepts", 10_000):
        errors.append(f"too many concepts: {len(concepts)}")
    for name, subtype in expected.get("entity_subtypes", {}).items():
        entity = entities.get(name.casefold())
        if entity and entity.subtype != subtype:
            errors.append(f"entity subtype: {name}={entity.subtype}")
    for name, subtype in expected.get("concept_subtypes", {}).items():
        concept = concepts.get(name.casefold())
        if concept and concept.subtype != subtype:
            errors.append(f"concept subtype: {name}={concept.subtype}")
    for name, aliases in expected.get("entity_aliases", {}).items():
        entity = entities.get(name.casefold())
        if entity:
            actual = {alias.casefold() for alias in entity.aliases}
            for alias in aliases:
                if alias.casefold() not in actual:
                    errors.append(f"missing alias: {name}/{alias}")
    mentions = {
        mention
        for item in [*result.entities, *result.concepts]
        for mention in item.mentions
    }
    for mention in expected.get("required_mentions", []):
        if mention not in mentions:
            errors.append(f"missing mention: {mention}")
    summary = result.source_summary.casefold()
    for term in expected.get("required_summary_terms", []):
        if term.casefold() not in summary:
            errors.append(f"missing summary term: {term}")
    return not errors, errors


def _prompt_revision() -> str:
    """Git Commit과 분류 코드·Prompt Hash를 결합한 Prompt 버전을 반환한다."""
    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    digest = hashlib.sha256()
    for path in (
        PROJECT_ROOT / "agent/wiki_builder/features/classification.py",
        PROJECT_ROOT / "agent/prompts/templates/personal_wiki_classifier.md",
    ):
        digest.update(path.read_bytes())
    return f"{completed.stdout.strip()}+{digest.hexdigest()[:12]}"


def main() -> None:
    """전체 케이스를 실행하고 선별 없이 Markdown 결과 파일을 작성한다."""
    args = _args()
    usage = Usage()
    client = ChatOpenAI(model=args.model, temperature=0)

    def tracked_complete(system_prompt: str, user_prompt: str, model: str) -> str:
        """LLM 응답 내용과 Usage Metadata를 함께 수집한다."""
        response = client.invoke([("system", system_prompt), ("human", user_prompt)])
        metadata = response.usage_metadata or {}
        usage.input_tokens += int(metadata.get("input_tokens", 0))
        usage.output_tokens += int(metadata.get("output_tokens", 0))
        return str(response.content).strip()

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
                result = classification.classify_source_for_wiki(
                    source_title=payload["title"],
                    source_content=payload["content"],
                    source_description=payload.get("description"),
                    source_tags=payload.get("tags", []),
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
    result_dir = ROOT / "results"
    result_dir.mkdir(exist_ok=True)
    safe_model = args.model.replace("/", "-")
    result_path = result_dir / f"{now.date().isoformat()}_{safe_model}.md"
    previous = sorted(path for path in result_dir.glob("*.md") if path != result_path)
    lines = [
        "# Personal Wiki Builder Benchmark",
        "",
        f"- 실행 날짜: {now.isoformat()}",
        f"- 모델: {args.model}",
        f"- 프롬프트 버전: {_prompt_revision()}",
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
