"""Personal Wiki V3 LLM 의미 감사 품질 벤치마크 실행기.

실제 OpenAI API로 모순·오래된 주장·누락 주제·전역 관계·지식 공백 판정을
평가하고 케이스별 정확도, 지연, Token과 전달받은 단가 기준 비용을 기록한다.
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
from agent.wiki_builder.features.identity_resolution import normalize_wiki_surface
from agent.wiki_builder.features.semantic_audit import (
    SEMANTIC_LINT_PROMPT_VERSION,
    audit_wiki_semantics,
    build_wiki_semantic_lint_prompt,
)
from agent.wiki_builder.features.semantic_lint import (
    WikiSemanticSourceDocument,
    build_wiki_semantic_lint_context,
)
from shared.wiki_models import ExistingWikiEntry

ROOT = Path(__file__).resolve().parent


@dataclass(slots=True)
class Usage:
    """벤치마크 전체 LLM Token 사용량을 누적한다."""

    input_tokens: int = 0
    output_tokens: int = 0


def _args() -> argparse.Namespace:
    """모델·단가와 무료 추정 모드 인자를 파싱한다."""
    parser = argparse.ArgumentParser(description="Wiki semantic lint benchmark")
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


def _entry(raw: dict[str, Any]) -> ExistingWikiEntry:
    """데이터셋 Page를 공유 Wiki 값 객체로 변환한다."""
    return ExistingWikiEntry(
        document_kind=str(raw["kind"]),
        document_key=str(raw["key"]),
        title=str(raw["title"]),
        domain=str(raw.get("domain") or "other"),
        summary=str(raw.get("summary") or ""),
        metadata={
            "aliases": list(raw.get("aliases") or []),
            "sources": list(raw.get("sources") or []),
            "related_entities": list(raw.get("related_entities") or []),
            "related_concepts": list(raw.get("related_concepts") or []),
        },
    )


def _context(case: dict[str, Any]):
    """평가 케이스를 실제 의미 감사 Context와 같은 구조로 만든다."""
    sources = [
        WikiSemanticSourceDocument(
            source_document_version_id=str(raw["id"]),
            title=str(raw["title"]),
            raw_content=str(raw["content"]),
            source_type=str(raw.get("source_type") or "document"),
        )
        for raw in case.get("sources", [])
    ]
    return build_wiki_semantic_lint_context(
        [_entry(raw) for raw in case.get("entries", [])],
        [],
        sources,
    )


def _estimate_tokens(cases: list[dict[str, Any]]) -> tuple[int, int, int]:
    """실행 승인 전에 볼 보수적인 API 호출·입출력 Token 상한을 계산한다."""
    system_prompt = (
        PROJECT_ROOT
        / "agent/prompts/templates/personal_wiki_semantic_lint.md"
    ).read_text(encoding="utf-8")
    input_chars = sum(
        len(system_prompt) + len(build_wiki_semantic_lint_prompt(_context(case)))
        for case in cases
    )
    return len(cases), input_chars // 2 + 1, len(cases) * 1_000


def _score(report: object, expected: dict[str, Any]) -> tuple[bool, list[str]]:
    """기대·금지 코드와 주제·관계·수집 조건으로 의미 감사 결과를 채점한다."""
    issues = tuple(getattr(report, "issues", ()))
    actual_codes = {issue.code.value for issue in issues}
    errors: list[str] = []
    required = set(expected.get("required_codes", []))
    if not required.issubset(actual_codes):
        errors.append(f"missing codes={sorted(required - actual_codes)}")
    required_any = set(expected.get("required_any_codes", []))
    if required_any and not actual_codes.intersection(required_any):
        errors.append(f"missing any code={sorted(required_any)}")
    forbidden = set(expected.get("forbidden_codes", []))
    if actual_codes.intersection(forbidden):
        errors.append(f"forbidden codes={sorted(actual_codes & forbidden)}")

    topic_any = {
        normalize_wiki_surface(str(value)) for value in expected.get("topic_any", [])
    }
    if topic_any:
        actual_topics = {
            normalize_wiki_surface(issue.topic.title)
            for issue in issues
            if issue.topic is not None
        }
        if not actual_topics.intersection(topic_any):
            errors.append(f"missing topic={sorted(topic_any)}")

    if expected.get("research_query") and not any(
        issue.research_query for issue in issues
    ):
        errors.append("missing research query")
    return not errors, errors


def _revision() -> str:
    """현재 Commit과 의미 감사 코드·Prompt·데이터셋 Hash를 결합한다."""
    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    digest = hashlib.sha256()
    for path in (
        PROJECT_ROOT / "agent/wiki_builder/features/semantic_audit.py",
        PROJECT_ROOT / "agent/prompts/templates/personal_wiki_semantic_lint.md",
        ROOT / "dataset.jsonl",
    ):
        digest.update(path.read_bytes())
    return f"{completed.stdout.strip()}+{digest.hexdigest()[:12]}"


def main() -> None:
    """데이터셋 전체를 실행하거나 실제 호출 없이 예상량만 출력한다."""
    args = _args()
    cases = _load_cases()
    call_count, estimated_input, estimated_output = _estimate_tokens(cases)
    if args.estimate_only:
        print(
            json.dumps(
                {
                    "case_count": len(cases),
                    "api_call_count": call_count,
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
        context = _context(case)
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
            report = audit_wiki_semantics(
                context,
                model=args.model,
                completion=tracked_complete,
            )
            # 채점 함수가 relation 참조를 제목으로 복원할 수 있도록 실행 중에만
            # 별도 Wrapper를 쓰지 않고 동등한 로컬 객체에 Page를 전달한다.
            relation_pages = set(case["expected"].get("relation_pages", []))
            passed, errors = _score_without_context(
                report,
                case["expected"],
                context=context,
                relation_pages=relation_pages,
            )
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
    result_path = result_dir / f"{now.date().isoformat()}_{args.model.replace('/', '-')}.md"
    previous = sorted(path for path in result_dir.glob("*.md") if path != result_path)
    lines = [
        "# Wiki Semantic Lint Benchmark",
        "",
        f"- 실행 날짜: {now.isoformat()}",
        f"- 모델: {args.model}",
        f"- 프롬프트 버전: {SEMANTIC_LINT_PROMPT_VERSION} ({_revision()})",
        f"- 케이스: {len(rows)} / 성공: {passed_count}",
        f"- 정확도: {passed_count / len(rows):.2%}",
        f"- 평균 지연시간: {total_latency / len(rows):.3f}s",
        f"- 입력 Token: {usage.input_tokens}",
        f"- 출력 Token: {usage.output_tokens}",
        f"- 비용: ${input_cost + output_cost:.6f}",
        f"- 이전 결과 비교: {previous[-1].name if previous else '비교 대상 없음'}",
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


def _score_without_context(
    report: object,
    expected: dict[str, Any],
    *,
    context: object,
    relation_pages: set[str],
) -> tuple[bool, list[str]]:
    """기본 채점에 Context Page 제목 기반 관계 endpoint 조건을 더한다."""
    expected_without_relation = dict(expected)
    expected_without_relation.pop("relation_pages", None)
    passed, errors = _score(report, expected_without_relation)
    if not relation_pages:
        return passed, errors
    titles = {
        page.reference: page.title for page in getattr(context, "pages", ())
    }
    relation_matches = any(
        issue.relation is not None
        and {
            titles.get(issue.relation.source_page_reference),
            titles.get(issue.relation.target_page_reference),
        }
        == relation_pages
        for issue in getattr(report, "issues", ())
    )
    if not relation_matches:
        errors.append("missing expected relation endpoints")
    return not errors, errors


if __name__ == "__main__":
    main()
