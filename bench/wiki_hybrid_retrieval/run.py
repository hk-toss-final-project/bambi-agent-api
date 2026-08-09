"""개인 Wiki Keyword·Vector RRF의 의미 검색 품질과 비용을 실제 Embedding으로 평가한다.

실제 API 비용이 발생하므로 예상 토큰·비용을 먼저 출력하고, --confirm-cost를
명시한 경우에만 10개 이상 케이스를 실행해 results/에 기록한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parents[1]
DATASET = ROOT / "dataset.jsonl"
RESULTS = ROOT / "results"

load_dotenv(PROJECT_ROOT / ".env")
sys.path.insert(0, str(PROJECT_ROOT))

from agent.llm.api import embed_texts  # noqa: E402
from agent.selection.api import cosine_similarity  # noqa: E402
from domain.personal_wiki.retrieval.api import prag_004  # noqa: E402
from shared.report_models import ReportContextDocument  # noqa: E402


def load_cases() -> list[dict[str, Any]]:
    """JSONL 데이터셋을 읽고 실제 평가 최소 10개 케이스를 강제한다."""
    cases = [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(cases) < 10:
        raise ValueError("Wiki Hybrid 검색 벤치마크는 최소 10개 케이스가 필요합니다.")
    return cases


def estimate_input_tokens(cases: list[dict[str, Any]]) -> int:
    """다국어 입력에서 비용을 과소 추정하지 않도록 문자 수 기준 상한을 계산한다."""
    characters = sum(
        len(str(case["query"]))
        + sum(len(str(candidate["text"])) for candidate in case["candidates"])
        for case in cases
    )
    return max(1, characters)


def calculate_cost(input_tokens: int, *, cost_per_million: float) -> float:
    """Embedding 입력 토큰 추정치와 단가로 예상·측정 비용을 계산한다."""
    return input_tokens * cost_per_million / 1_000_000


def _context(candidate: dict[str, Any], *, score: float) -> ReportContextDocument:
    """Fixture 후보를 RRF가 소비할 개인 Wiki Context로 변환한다."""
    identifier = str(candidate["id"])
    return ReportContextDocument(
        reference=f"P-{identifier}",
        document_version_id=f"version-{identifier}",
        chunk_id=f"chunk-{identifier}",
        namespace_key="user/benchmark",
        title=str(candidate["title"]),
        content=str(candidate["text"]),
        url=None,
        score=score,
        context_role="semantic_retrieval",
    )


def current_revision() -> str:
    """결과 재현에 쓸 현재 Git 해시와 Working Tree 상태를 반환한다."""
    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    suffix = "+dirty" if status.stdout.strip() else ""
    return completed.stdout.strip() + suffix


def evaluate_case(case: dict[str, Any], *, model: str) -> dict[str, Any]:
    """실제 Embedding Vector 순위와 Keyword 순위를 RRF로 합쳐 Recall을 채점한다."""
    candidates = {
        str(candidate["id"]): candidate for candidate in case["candidates"]
    }
    texts = [
        str(case["query"]),
        *(str(candidate["text"]) for candidate in case["candidates"]),
    ]
    started = time.perf_counter()
    vectors = embed_texts(texts, model=model, dimensions=1536)
    latency_ms = int((time.perf_counter() - started) * 1_000)
    query_vector, candidate_vectors = vectors[0], vectors[1:]
    vector_ranked = sorted(
        zip(case["candidates"], candidate_vectors, strict=True),
        key=lambda item: cosine_similarity(query_vector, item[1]),
        reverse=True,
    )
    vector_contexts = [
        _context(
            candidate,
            score=max(0.05, cosine_similarity(query_vector, vector)),
        )
        for candidate, vector in vector_ranked
    ]
    keyword_contexts = [
        _context(candidates[identifier], score=0.5)
        for identifier in case["keyword_order"]
        if identifier in candidates
    ]
    fused = asyncio.run(prag_004(keyword_contexts, vector_contexts, top_k=3))
    fused_ids = [context.chunk_id.removeprefix("chunk-") for context in fused]
    expected = {str(identifier) for identifier in case["expected_ids"]}
    hits = expected.intersection(fused_ids)
    return {
        "id": case["id"],
        "passed": len(hits) >= int(case.get("min_expected_hits", 1)),
        "expected": sorted(expected),
        "vector_top": [
            str(candidate["id"]) for candidate, _vector in vector_ranked[:3]
        ],
        "fused_top": fused_ids,
        "hits": sorted(hits),
        "latency_ms": latency_ms,
        "estimated_input_tokens": estimate_input_tokens([case]),
    }


def write_result(
    results: list[dict[str, Any]],
    *,
    model: str,
    revision: str,
    cost_per_million: float,
) -> Path:
    """케이스별 Recall·지연·토큰·비용을 Markdown 결과로 기록한다."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    safe_model = model.replace("/", "-")
    path = RESULTS / f"{now.date().isoformat()}_{safe_model}.md"
    passed = sum(int(result["passed"]) for result in results)
    tokens = sum(int(result["estimated_input_tokens"]) for result in results)
    latency = sum(int(result["latency_ms"]) for result in results) / len(results)
    cost = calculate_cost(tokens, cost_per_million=cost_per_million)
    lines = [
        "# 개인 Wiki Hybrid 검색 벤치마크",
        "",
        f"- 실행 시각(UTC): {now.isoformat()}",
        f"- Embedding 모델: `{model}` (1536 dimensions)",
        f"- 구현 버전(커밋): `{revision}`",
        f"- Recall 성공: {passed}/{len(results)} ({passed / len(results):.1%})",
        f"- 평균 Embedding 지연: {latency:.0f}ms",
        f"- 추정 입력 토큰: {tokens}",
        f"- 추정 비용: ${cost:.6f} (${cost_per_million}/1M tokens)",
        "",
        "| 케이스 | 결과 | 기대 | Vector top-3 | RRF top-3 | 지연(ms) |",
        "|---|---:|---|---|---|---:|",
    ]
    for result in results:
        lines.append(
            "| {id} | {status} | {expected} | {vector} | {fused} | {latency} |".format(
                id=result["id"],
                status="PASS" if result["passed"] else "FAIL",
                expected=", ".join(result["expected"]),
                vector=", ".join(result["vector_top"]),
                fused=", ".join(result["fused_top"]),
                latency=result["latency_ms"],
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    """비용 승인을 확인한 뒤 전체 Hybrid 검색 벤치마크를 실행한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="text-embedding-3-small")
    parser.add_argument("--confirm-cost", action="store_true")
    parser.add_argument("--cost-per-million", type=float, default=0.02)
    args = parser.parse_args()
    cases = load_cases()
    estimated_tokens = estimate_input_tokens(cases)
    estimated_cost = calculate_cost(
        estimated_tokens, cost_per_million=args.cost_per_million
    )
    print(
        f"cases={len(cases)}, estimated_input_tokens<={estimated_tokens}, "
        f"estimated_cost<=${estimated_cost:.6f}"
    )
    if not args.confirm_cost:
        print("실제 호출은 비용 고지 후 --confirm-cost를 추가해야 합니다.")
        return
    results = [evaluate_case(case, model=args.model) for case in cases]
    path = write_result(
        results,
        model=args.model,
        revision=current_revision(),
        cost_per_million=args.cost_per_million,
    )
    print(f"result={path}")
    if not all(result["passed"] for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
