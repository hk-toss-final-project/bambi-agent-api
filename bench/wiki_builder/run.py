"""개인 Wiki 분류(classify_source_for_wiki) 벤치마크 실행기.

전체 오케스트레이션(build_incremental_wiki/rebuild_full_wiki)은 DB
Connection과 Transaction을 요구해 벤치마크로 그대로 돌리기 어렵다. 품질을
좌우하는 것은 원문을 entity·concept으로 분류하는 단일 LLM 호출
(classify_source_for_wiki)이므로, 이 함수를 topic_intent와 같은 방식으로
직접 호출해 벤치마크한다.

실제 OpenAI API를 호출하며 케이스별 성공·실패, 지연시간, 토큰 사용량과
예상 비용을 results/에 기록한다.

실행:
    uv run python bench/wiki_builder/run.py --estimate-only

    uv run python bench/wiki_builder/run.py \\
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
from agent.wiki_builder.api import classify_source_for_wiki
from agent.wiki_builder.features import classification as wiki_classification
from shared.wiki_models import ExistingWikiEntry

ROOT = Path(__file__).resolve().parent

# 실제 호출 없이 대략적인 입력 규모를 가늠할 때 쓰는 문자당 Token 비율.
# 한국어·영어가 섞인 프롬프트 기준 대략치이며, --estimate-only 전용이다.
_ESTIMATE_CHARS_PER_TOKEN = 2.5

# LangSmith Datasets & Experiments 탭에 동기화할 데이터셋 이름.
_LANGSMITH_DATASET_NAME = "bambi-wiki-builder-classify"


@dataclass(slots=True)
class Usage:
    """벤치마크 전체의 입력·출력 토큰을 누적한다."""

    input_tokens: int = 0
    output_tokens: int = 0


def _args() -> argparse.Namespace:
    """모델, 토큰 단가, estimate-only 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(
        description="개인 Wiki 분류(classify_source_for_wiki) 벤치마크"
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


def _existing_entries(raw_entries: list[dict[str, object]]) -> list[ExistingWikiEntry]:
    """케이스 JSON의 기존 entity·concept 목록을 값 객체로 변환한다."""
    return [
        ExistingWikiEntry(
            document_kind=str(entry["document_kind"]),
            document_key=str(entry["document_key"]),
            title=str(entry["title"]),
            domain=entry.get("domain"),
            summary=entry.get("summary"),
            metadata=dict(entry.get("metadata") or {}),
        )
        for entry in raw_entries
    ]


def _prompt_version() -> str:
    """현재 커밋과 분류 프롬프트 내용으로 재현 가능한 버전 표기를 만든다."""
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
        wiki_classification._SYSTEM_PROMPT.encode("utf-8")
    ).hexdigest()[:12]
    return f"{commit}+{digest}"


def _matches(expected_name: str, names: list[str]) -> bool:
    """기대 이름이 실제 이름·별칭 목록 중 하나와 대소문자 무시 부분일치하는지 본다."""
    marker = expected_name.strip().casefold()
    return any(marker in name.casefold() or name.casefold() in marker for name in names)


def _grade(
    case: dict[str, object], classification: object
) -> tuple[bool, list[str]]:
    """기대 entity·concept이 분류 결과에 모두 나타났는지 채점한다."""
    entity_names = [
        name
        for entity in classification.entities
        for name in [entity.name, *entity.aliases]
    ]
    concept_titles = [
        title
        for concept in classification.concepts
        for title in [concept.title, *concept.aliases]
    ]
    missing: list[str] = []
    for expected in case.get("expected_entities", []) or []:
        if not _matches(str(expected["name"]), entity_names):
            missing.append(f"entity:{expected['name']}")
    for expected in case.get("expected_concepts", []) or []:
        if not _matches(str(expected["title"]), concept_titles):
            missing.append(f"concept:{expected['title']}")
    return (not missing, missing)


def _estimate_tokens(cases: list[dict[str, object]]) -> int:
    """실제 호출 없이 프롬프트 문자수 기준 대략적인 입력 Token을 추정한다."""
    system_chars = len(wiki_classification._SYSTEM_PROMPT)
    total_chars = 0
    for case in cases:
        total_chars += system_chars
        total_chars += len(str(case.get("source_title", "")))
        total_chars += len(str(case.get("source_content", "")))
        total_chars += len(str(case.get("source_description", "") or ""))
    return int(total_chars / _ESTIMATE_CHARS_PER_TOKEN)


def _classification_to_dict(classification: object) -> dict[str, object]:
    """분류 결과를 LangSmith Run Output으로 남길 수 있는 순수 dict로 변환한다."""
    return {
        "entities": [
            {"name": entity.name, "aliases": list(entity.aliases)}
            for entity in classification.entities
        ],
        "concepts": [
            {"title": concept.title, "aliases": list(concept.aliases)}
            for concept in classification.concepts
        ],
    }


def _make_langsmith_target(model: str):
    """LangSmith Example의 inputs를 받아 분류를 실행하는 target 함수를 만든다."""

    def target(inputs: dict[str, object]) -> dict[str, object]:
        classification = classify_source_for_wiki(
            source_title=str(inputs["source_title"]),
            source_content=str(inputs["source_content"]),
            source_description=inputs.get("source_description"),
            source_tags=inputs.get("source_tags") or [],
            existing_entities=_existing_entries(
                inputs.get("existing_entities", []) or []
            ),
            existing_concepts=_existing_entries(
                inputs.get("existing_concepts", []) or []
            ),
            model=model,
        )
        return _classification_to_dict(classification)

    return target


def _langsmith_accuracy_evaluator(
    outputs: dict[str, object], reference_outputs: dict[str, object]
) -> dict[str, object]:
    """기대 entity·concept이 분류 결과에 모두 나타났는지 LangSmith Evaluator로 채점한다."""
    entity_names = [
        name
        for entity in outputs.get("entities", [])
        for name in [entity["name"], *entity.get("aliases", [])]
    ]
    concept_titles = [
        title
        for concept in outputs.get("concepts", [])
        for title in [concept["title"], *concept.get("aliases", [])]
    ]
    missing: list[str] = []
    for expected in reference_outputs.get("expected_entities", []) or []:
        if not _matches(str(expected["name"]), entity_names):
            missing.append(f"entity:{expected['name']}")
    for expected in reference_outputs.get("expected_concepts", []) or []:
        if not _matches(str(expected["title"]), concept_titles):
            missing.append(f"concept:{expected['title']}")
    return {
        "key": "accuracy",
        "score": 0.0 if missing else 1.0,
        "comment": ", ".join(missing) if missing else "기대 entity·concept 모두 확인됨",
    }


def _ensure_langsmith_dataset(client: Client, cases: list[dict[str, object]]) -> str:
    """dataset.jsonl 케이스를 LangSmith Dataset으로 최초 1회 동기화하고 이름을 반환한다."""
    if client.has_dataset(dataset_name=_LANGSMITH_DATASET_NAME):
        return _LANGSMITH_DATASET_NAME

    dataset = client.create_dataset(
        _LANGSMITH_DATASET_NAME,
        description=(
            "개인 Wiki 분류(classify_source_for_wiki) 벤치마크 케이스. "
            "bench/wiki_builder/dataset.jsonl과 최초 실행 시 동기화됨."
        ),
    )
    examples = [
        {
            "inputs": {
                key: value
                for key, value in case.items()
                if key not in ("id", "expected_entities", "expected_concepts")
            },
            "outputs": {
                "expected_entities": case.get("expected_entities", []),
                "expected_concepts": case.get("expected_concepts", []),
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
        evaluators=[_langsmith_accuracy_evaluator],
        experiment_prefix=f"wiki-builder-{model}",
        metadata={"bench": "wiki_builder", "model": model},
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
    """모든 케이스를 분류하고 결과를 results/에 기록한다."""
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
                tags=["bench:wiki_builder", f"model:{args.model}"],
                metadata={
                    "bench": "wiki_builder",
                    "model": args.model,
                    "case_id": str(case["id"]),
                },
            ),
            capture_llm_calls() as observations,
        ):
            classification = classify_source_for_wiki(
                source_title=str(case["source_title"]),
                source_content=str(case["source_content"]),
                source_description=case.get("source_description"),
                source_tags=case.get("source_tags") or [],
                existing_entities=_existing_entries(
                    case.get("existing_entities", []) or []
                ),
                existing_concepts=_existing_entries(
                    case.get("existing_concepts", []) or []
                ),
                model=args.model,
            )
        elapsed = time.monotonic() - started
        latencies.append(elapsed)
        for observation in observations:
            usage.input_tokens += observation.input_tokens
            usage.output_tokens += observation.output_tokens
        ok, missing = _grade(case, classification)
        rows.append((str(case["id"]), ok, missing, elapsed))

    passed = sum(1 for _, ok, _, _ in rows if ok)
    cost = (
        usage.input_tokens * args.input_cost_per_million
        + usage.output_tokens * args.output_cost_per_million
    ) / 1_000_000

    lines = [
        "# 개인 Wiki 분류(classify_source_for_wiki) 벤치마크",
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
        "| 케이스 | 결과 | 누락 항목 | 지연 |",
        "|---|---|---|---:|",
    ]
    for case_id, ok, missing, elapsed in rows:
        missing_text = ", ".join(missing) if missing else "-"
        lines.append(
            f"| {case_id} | {'PASS' if ok else 'FAIL'} | {missing_text} | {elapsed:.2f}s |"
        )

    results = ROOT / "results"
    results.mkdir(exist_ok=True)
    out = results / f"{datetime.now(UTC):%Y-%m-%d}_{args.model}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
