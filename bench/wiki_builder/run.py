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

from dotenv import load_dotenv

# OPENAI_API_KEY를 .env에서 읽는다(앱 진입점과 같은 방식).
load_dotenv(PROJECT_ROOT / ".env")

from agent.llm.api import complete_with_usage
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


def _relation_signature(relation: object) -> tuple[str, str, str, str, str]:
    """관계 객체를 대소문자에 무관한 채점용 Signature로 변환한다."""
    return (
        str(getattr(relation, "source_kind")).casefold(),
        str(getattr(relation, "source_name")).casefold(),
        str(getattr(relation, "target_kind")).casefold(),
        str(getattr(relation, "target_name")).casefold(),
        str(getattr(relation, "relation_type")).casefold(),
    )


def _expected_relation_signature(
    relation: dict[str, str],
) -> tuple[str, str, str, str, str]:
    """Dataset 관계 기대값을 실제 결과와 같은 Signature로 변환한다."""
    return (
        relation["source_kind"].casefold(),
        relation["source_name"].casefold(),
        relation["target_kind"].casefold(),
        relation["target_name"].casefold(),
        relation["relation_type"].casefold(),
    )


def _reversed_signature(
    signature: tuple[str, str, str, str, str],
) -> tuple[str, str, str, str, str]:
    """방향만 뒤집은 관계 Signature를 만든다."""
    source_kind, source_name, target_kind, target_name, relation_type = signature
    return (target_kind, target_name, source_kind, source_name, relation_type)


def _score(
    result: object, expected: dict[str, Any]
) -> tuple[bool, list[str], dict[str, int]]:
    """노드·관계 추출 결과를 Dataset의 품질 기준으로 채점한다."""
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
    # 노드가 원문에서 맡은 역할. 관심사 후보가 되는 기준은 subject냐 아니냐
    # 하나뿐이라, 비-subject끼리(tool·source·mention) 갈리는 것은 통과로 본다.
    # 노드가 아예 안 뽑힌 경우도 마찬가지다 — 관심사가 될 수 없기 때문이다.
    # 반대로 subject를 기대한 노드는 실제로 뽑혀서 subject여야 한다. 못 뽑으면
    # 사용자의 진짜 관심사를 잃는다.
    #
    # (2026-08-08: 처음에는 역할이 정확히 일치해야 통과로 짰는데, 목적과
    # 어긋나 OpenWiki=mention·"API 키 발급" 미추출이 실패로 잡혔다. 둘 다
    # 관심사에서 빠지므로 의도한 결과다.)
    for name, role in expected.get("node_roles", {}).items():
        node = entities.get(name.casefold()) or concepts.get(name.casefold())
        if role == "subject":
            if node is None:
                errors.append(f"missing node for role: {name}")
            elif node.role != "subject":
                errors.append(f"node role: {name}={node.role} (expected subject)")
        elif node is not None and node.role == "subject":
            errors.append(f"node role: {name}=subject (expected non-subject)")
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
    relations = {_relation_signature(relation) for relation in result.relations}
    stats = {"tp": 0, "fn": 0, "forbidden_hit": 0, "reversed_only": 0}
    for expected_relation in expected.get("relations", []):
        signature = _expected_relation_signature(expected_relation)
        if signature in relations:
            stats["tp"] += 1
            continue
        stats["fn"] += 1
        # 옵시디언 위키링크는 방향이 모호할 수 있어 역방향 일치를 따로 센다.
        if _reversed_signature(signature) in relations:
            stats["reversed_only"] += 1
        errors.append(
            "missing relation: "
            f"{expected_relation['source_name']} -> "
            f"{expected_relation['target_name']} / "
            f"{expected_relation['relation_type']}"
        )
    for forbidden in expected.get("forbidden_relations", []):
        signature = _expected_relation_signature(forbidden)
        if signature in relations or _reversed_signature(signature) in relations:
            stats["forbidden_hit"] += 1
            errors.append(
                "forbidden relation: "
                f"{forbidden['source_name']} -> {forbidden['target_name']}"
            )
    judged = len(expected.get("relations", [])) + len(
        expected.get("forbidden_relations", [])
    )
    stats["unjudged"] = max(0, len(relations) - stats["tp"] - stats["forbidden_hit"])
    stats["judged"] = judged
    if len(relations) > expected.get("max_relations", 10_000):
        errors.append(f"too many relations: {len(relations)}")
    return not errors, errors, stats


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
        PROJECT_ROOT / "agent/wiki_builder/features/relations.py",
        PROJECT_ROOT / "agent/prompts/templates/personal_wiki_classifier.md",
        PROJECT_ROOT
        / "agent/prompts/templates/personal_wiki_relation_reviewer.md",
    ):
        digest.update(path.read_bytes())
    return f"{completed.stdout.strip()}+{digest.hexdigest()[:12]}"


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
                result = classification.classify_source_for_wiki(
                    source_title=payload["title"],
                    source_content=payload["content"],
                    source_description=payload.get("description"),
                    source_tags=payload.get("tags", []),
                    existing_entities=[],
                    existing_concepts=[],
                    model=args.model,
                )
                passed, errors, stats = _score(result, case["expected"])
            except Exception as error:
                passed = False
                errors = [f"{type(error).__name__}: {error}"]
                expected = case["expected"]
                stats = {
                    "tp": 0,
                    "fn": len(expected.get("relations", [])),
                    "forbidden_hit": 0,
                    "reversed_only": 0,
                    "unjudged": 0,
                    "judged": 0,
                }
            rows.append(
                {
                    "id": case["id"],
                    "passed": passed,
                    "errors": errors,
                    "stats": stats,
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
    tp = sum(int(row["stats"]["tp"]) for row in rows)
    fn = sum(int(row["stats"]["fn"]) for row in rows)
    forbidden_hit = sum(int(row["stats"]["forbidden_hit"]) for row in rows)
    reversed_only = sum(int(row["stats"]["reversed_only"]) for row in rows)
    unjudged = sum(int(row["stats"]["unjudged"]) for row in rows)
    recall = tp / (tp + fn) if tp + fn else 0.0
    precision = tp / (tp + forbidden_hit) if tp + forbidden_hit else 0.0
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
        f"- 정확도(케이스 전체 통과): {passed_count / len(rows):.2%}",
        f"- 연결 Recall: {recall:.2%} — 정답 연결 {tp}/{tp + fn}건 생성",
        f"- 연결 Precision(판정 가능 범위): {precision:.2%} — 금지 연결 위반 {forbidden_hit}건",
        f"- 방향만 다른 일치: {reversed_only}건 (정답지와 반대 방향)",
        f"- 정답지 밖 연결: {unjudged}건 (판정 대상 아님)",
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
