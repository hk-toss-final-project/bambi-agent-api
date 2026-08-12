"""Report Builder 콘텐츠 생성(generate_report_content) 벤치마크 실행기.

REPORT-001/002/007~010(agent/report_builder/features/orchestration.py)은
FeatureRequest에 주입된 구현을 실행하는 얇은 Facade일 뿐, 실제 LLM 호출은
generation.generate_report_content에서 일어난다. 검색(retrieval.py)과
Citation 검증(citations 재노출)은 이 함수의 입력·출력 경계에 이미 반영돼
있으므로, topic_intent와 같은 방식으로 이 함수를 직접 호출해 벤치마크한다.

실제 OpenAI API를 호출하며 케이스별 성공·실패, 지연시간, 토큰 사용량과
예상 비용을 results/에 기록한다.

실행:
    uv run python bench/report_builder/run.py --estimate-only

    uv run python bench/report_builder/run.py \\
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

# OPENAI_API_KEY를 .env에서 읽는다(앱 진입점·다른 벤치마크와 같은 방식).
load_dotenv(PROJECT_ROOT / ".env")

from langsmith import Client
from langsmith.evaluation import evaluate
from langsmith.run_helpers import tracing_context

from agent.llm.api import capture_llm_calls
from agent.report_builder.api import ReportContextDocument, generate_report_content
from agent.report_builder.features import generation as report_generation

ROOT = Path(__file__).resolve().parent

# LangSmith Datasets & Experiments 탭에 동기화할 데이터셋 이름.
_LANGSMITH_DATASET_NAME = "bambi-report-builder-generate"

# 실제 호출 없이 대략적인 입력 규모를 가늠할 때 쓰는 문자당 Token 비율.
# 한국어·영어가 섞인 프롬프트 기준 대략치이며, --estimate-only 전용이다.
_ESTIMATE_CHARS_PER_TOKEN = 2.5


@dataclass(slots=True)
class Usage:
    """벤치마크 전체의 입력·출력 토큰을 누적한다."""

    input_tokens: int = 0
    output_tokens: int = 0


def _args() -> argparse.Namespace:
    """모델, 토큰 단가, estimate-only 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(
        description="Report Builder 생성(generate_report_content) 벤치마크"
    )
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--input-cost-per-million", type=float, default=None)
    parser.add_argument("--output-cost-per-million", type=float, default=None)
    parser.add_argument(
        "--estimate-only",
        action="store_true",
        help="LLM을 호출하지 않고 케이스 수·모델·대략적 Token 규모만 출력한다.",
    )
    parser.add_argument(
        "--langsmith-experiment",
        action="store_true",
        help=(
            "로컬 results/ 기록 대신 LangSmith Dataset을 만들고(최초 1회) "
            "그 Dataset에 대한 Experiment로 실행해 Datasets & Experiments 탭에서 "
            "모델별로 나란히 비교할 수 있게 한다."
        ),
    )
    args = parser.parse_args()
    if not args.estimate_only and not args.langsmith_experiment and (
        args.input_cost_per_million is None or args.output_cost_per_million is None
    ):
        parser.error(
            "--estimate-only가 아니면 --input-cost-per-million과 "
            "--output-cost-per-million이 필요합니다."
        )
    return args


def _load_cases() -> list[dict[str, object]]:
    """dataset.jsonl의 평가 케이스를 읽는다."""
    lines = (ROOT / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _contexts(case: dict[str, object]) -> list[ReportContextDocument]:
    """케이스 JSON의 근거 목록을 ReportContextDocument 값 객체로 변환한다."""
    documents: list[ReportContextDocument] = []
    for raw in case["contexts"]:
        reference = str(raw["reference"])
        documents.append(
            ReportContextDocument(
                reference=reference,
                document_version_id=str(
                    raw.get("document_version_id") or f"bench-{case['id']}-{reference}"
                ),
                chunk_id=str(raw.get("chunk_id") or f"bench-{case['id']}-{reference}-c1"),
                namespace_key=str(raw["namespace_key"]),
                title=str(raw["title"]),
                content=str(raw["content"]),
                url=raw.get("url"),
                score=float(raw.get("score", 1.0)),
                context_role=str(raw.get("context_role", "retrieved")),
                source_updated_at=raw.get("source_updated_at"),
            )
        )
    return documents


def _prompt_version() -> str:
    """현재 커밋과 생성 시스템 프롬프트 내용으로 재현 가능한 버전 표기를 만든다."""
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

    digest = hashlib.sha256(
        report_generation._SYSTEM_PROMPT.encode("utf-8")
    ).hexdigest()[:12]
    return f"{commit}+{digest}"


def _grade(case: dict[str, object], content: object) -> tuple[bool, list[str]]:
    """기대 키워드 포함·금지어 배제·인용 존재 여부를 채점한다."""
    haystack = f"{content.title}\n{content.summary}\n{content.body}".casefold()
    problems: list[str] = []
    for keyword in case.get("expected_keywords", []) or []:
        if str(keyword).casefold() not in haystack:
            problems.append(f"missing:{keyword}")
    for forbidden in case.get("must_not_contain", []) or []:
        if str(forbidden).casefold() in haystack:
            problems.append(f"forbidden:{forbidden}")
    if not content.citation_references:
        problems.append("no-citations")
    return (not problems, problems)


def _estimate_tokens(cases: list[dict[str, object]]) -> int:
    """실제 호출 없이 프롬프트 문자수 기준 대략적인 입력 Token을 추정한다."""
    system_chars = len(report_generation._SYSTEM_PROMPT)
    total_chars = 0
    for case in cases:
        total_chars += system_chars
        total_chars += len(str(case.get("topic", "")))
        for context in case.get("contexts", []) or []:
            total_chars += len(str(context.get("title", "")))
            total_chars += len(str(context.get("content", "")))
    return int(total_chars / _ESTIMATE_CHARS_PER_TOKEN)


def _content_to_dict(content: object) -> dict[str, object]:
    """생성 결과를 LangSmith Run Output으로 남길 수 있는 순수 dict로 변환한다."""
    return {
        "title": content.title,
        "summary": content.summary,
        "body": content.body,
        "citation_references": list(content.citation_references),
    }


def _make_langsmith_target(model: str):
    """LangSmith Example의 inputs를 받아 콘텐츠 생성을 실행하는 target 함수를 만든다."""

    def target(inputs: dict[str, object]) -> dict[str, object]:
        content = generate_report_content(
            topic=str(inputs["topic"]),
            content_type=str(inputs["content_type"]),
            language=str(inputs["language"]),
            contexts=_contexts(inputs),
            model=model,
            topics=inputs.get("topics") or (),
            interest_bundle=inputs.get("interest_bundle"),
        )
        return _content_to_dict(content)

    return target


def _langsmith_quality_evaluator(
    outputs: dict[str, object], reference_outputs: dict[str, object]
) -> dict[str, object]:
    """기대 키워드 포함·금지어 배제·인용 존재 여부를 LangSmith Evaluator로 채점한다."""
    haystack = f"{outputs['title']}\n{outputs['summary']}\n{outputs['body']}".casefold()
    problems: list[str] = []
    for keyword in reference_outputs.get("expected_keywords", []) or []:
        if str(keyword).casefold() not in haystack:
            problems.append(f"missing:{keyword}")
    for forbidden in reference_outputs.get("must_not_contain", []) or []:
        if str(forbidden).casefold() in haystack:
            problems.append(f"forbidden:{forbidden}")
    if not outputs.get("citation_references"):
        problems.append("no-citations")
    return {
        "key": "quality",
        "score": 0.0 if problems else 1.0,
        "comment": ", ".join(problems) if problems else "키워드·인용 조건 모두 통과",
    }


def _ensure_langsmith_dataset(client: Client, cases: list[dict[str, object]]) -> str:
    """dataset.jsonl 케이스를 LangSmith Dataset으로 최초 1회 동기화하고 이름을 반환한다."""
    if client.has_dataset(dataset_name=_LANGSMITH_DATASET_NAME):
        return _LANGSMITH_DATASET_NAME

    dataset = client.create_dataset(
        _LANGSMITH_DATASET_NAME,
        description=(
            "Report Builder 생성(generate_report_content) 벤치마크 케이스. "
            "bench/report_builder/dataset.jsonl과 최초 실행 시 동기화됨."
        ),
    )
    examples = [
        {
            "inputs": {
                key: value
                for key, value in case.items()
                if key not in ("expected_keywords", "must_not_contain", "note")
            },
            "outputs": {
                "expected_keywords": case.get("expected_keywords", []),
                "must_not_contain": case.get("must_not_contain", []),
            },
            "metadata": {"case_id": case["id"]},
        }
        for case in cases
    ]
    client.create_examples(dataset_id=dataset.id, examples=examples)
    return _LANGSMITH_DATASET_NAME


def _run_langsmith_experiment(cases: list[dict[str, object]], model: str) -> int:
    """LangSmith Dataset에 대한 Experiment로 실행해 Datasets & Experiments 탭에 남긴다."""
    client = Client()
    dataset_name = _ensure_langsmith_dataset(client, cases)
    results = evaluate(
        _make_langsmith_target(model),
        data=dataset_name,
        evaluators=[_langsmith_quality_evaluator],
        experiment_prefix=f"report-builder-{model}",
        metadata={"bench": "report_builder", "model": model},
        client=client,
    )
    experiment_name = getattr(results, "experiment_name", None) or str(results)
    print(f"[langsmith] Dataset '{dataset_name}'에 Experiment '{experiment_name}' 기록 완료.")
    print(
        "[langsmith] LangSmith → Datasets & Experiments → "
        f"{dataset_name}에서 모델별 Experiment를 나란히 비교할 수 있습니다."
    )
    return 0


def main() -> int:
    """모든 케이스를 생성하고 결과를 results/에 기록한다."""
    args = _args()
    cases = _load_cases()

    if args.estimate_only:
        estimated_input_tokens = _estimate_tokens(cases)
        print(
            f"[estimate-only] {len(cases)}개 케이스를 모델 {args.model}로 실행할 예정입니다. "
            f"LLM 호출은 하지 않았습니다."
        )
        print(f"[estimate-only] 대략적 입력 Token 추정치: {estimated_input_tokens}")
        if args.input_cost_per_million and args.output_cost_per_million:
            rough_cost = (
                estimated_input_tokens * args.input_cost_per_million
            ) / 1_000_000
            print(f"[estimate-only] 대략적 입력 비용 추정치: ${rough_cost:.6f} (출력 제외)")
        return 0

    if args.langsmith_experiment:
        return _run_langsmith_experiment(cases, args.model)

    usage = Usage()
    rows: list[tuple[str, bool, list[str], float]] = []
    latencies: list[float] = []

    for case in cases:
        started = time.monotonic()
        # LangSmith 대시보드에서 모델·벤치 이름으로 필터링할 수 있도록 태그를 남긴다.
        with (
            tracing_context(
                tags=["bench:report_builder", f"model:{args.model}"],
                metadata={
                    "bench": "report_builder",
                    "model": args.model,
                    "case_id": str(case["id"]),
                },
            ),
            capture_llm_calls() as observations,
        ):
            content = generate_report_content(
                topic=str(case["topic"]),
                content_type=str(case["content_type"]),
                language=str(case["language"]),
                contexts=_contexts(case),
                model=args.model,
                topics=case.get("topics") or (),
                interest_bundle=case.get("interest_bundle"),
            )
        elapsed = time.monotonic() - started
        latencies.append(elapsed)
        for observation in observations:
            usage.input_tokens += observation.input_tokens
            usage.output_tokens += observation.output_tokens
        ok, problems = _grade(case, content)
        rows.append((str(case["id"]), ok, problems, elapsed))

    passed = sum(1 for _, ok, _, _ in rows if ok)
    cost = (
        usage.input_tokens * args.input_cost_per_million
        + usage.output_tokens * args.output_cost_per_million
    ) / 1_000_000

    lines = [
        "# Report Builder 생성(generate_report_content) 벤치마크",
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
        "| 케이스 | 결과 | 문제 | 지연 |",
        "|---|---|---|---:|",
    ]
    for case_id, ok, problems, elapsed in rows:
        problem_text = ", ".join(problems) if problems else "-"
        lines.append(
            f"| {case_id} | {'PASS' if ok else 'FAIL'} | {problem_text} | {elapsed:.2f}s |"
        )

    results = ROOT / "results"
    results.mkdir(exist_ok=True)
    out = results / f"{datetime.now(UTC):%Y-%m-%d}_{args.model}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
