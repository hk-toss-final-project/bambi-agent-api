"""Wiki Embedding Batch 전환의 의미 유사도 품질 벤치마크 실행기.

Batch 전송 자체는 결정적 단위 테스트로 검증하고, 이 실행기는 실제 Embedding
모델이 한국어·영어·긴 입력·동명이의어에서 의미를 보존하는지 측정한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _args() -> argparse.Namespace:
    """모델·차원·단가와 무료 추정 모드 인자를 파싱한다."""
    parser = argparse.ArgumentParser(description="Wiki embedding batch benchmark")
    parser.add_argument("--model", default="text-embedding-3-small")
    parser.add_argument("--dimensions", type=int, default=1536)
    parser.add_argument("--input-cost-per-million", type=float)
    parser.add_argument("--estimate-only", action="store_true")
    args = parser.parse_args()
    if not args.estimate_only and args.input_cost_per_million is None:
        parser.error("실제 실행에는 입력 백만 Token당 단가가 필요합니다.")
    return args


def _load_cases() -> list[dict[str, Any]]:
    """JSONL 의미 유사도 평가 케이스를 순서대로 읽는다."""
    return [
        json.loads(line)
        for line in (ROOT / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _estimate_input_tokens(cases: list[dict[str, Any]]) -> int:
    """API 호출 승인 전에 볼 보수적인 입력 Token 상한을 계산한다."""
    characters = sum(len(case["left"]) + len(case["right"]) for case in cases)
    return characters // 2 + 1


def _cosine(left: list[float], right: list[float]) -> float:
    """두 Embedding Vector의 Cosine 유사도를 계산한다."""
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("Embedding Vector의 Norm은 0이면 안 됩니다.")
    return numerator / (left_norm * right_norm)


def _revision() -> str:
    """현재 Commit과 Batch Embedding 구현 Hash로 실행 버전을 만든다."""
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    digest = hashlib.sha256(
        (PROJECT_ROOT / "agent/wiki_builder/features/embeddings.py").read_bytes()
    ).hexdigest()[:12]
    return f"{commit}+{digest}"


def _passed(similarity: float, expected: dict[str, Any]) -> bool:
    """기대 관계별 최소·최대 유사도 기준을 판정한다."""
    threshold = float(expected["threshold"])
    if expected["relation"] == "similar":
        return similarity >= threshold
    return similarity <= threshold


def main() -> int:
    """전체 케이스를 한 Embedding 요청으로 실행하거나 예상량만 출력한다."""
    args = _args()
    cases = _load_cases()
    estimated_tokens = _estimate_input_tokens(cases)
    if args.estimate_only:
        print(
            json.dumps(
                {
                    "case_count": len(cases),
                    "api_call_count": 1,
                    "embedding_input_count": len(cases) * 2,
                    "estimated_input_tokens_upper": estimated_tokens,
                },
                ensure_ascii=False,
            )
        )
        return 0

    from openai import OpenAI

    texts = [text for case in cases for text in (case["left"], case["right"])]
    started = time.perf_counter()
    response = OpenAI(max_retries=0).embeddings.create(
        model=args.model,
        input=texts,
        dimensions=args.dimensions,
    )
    elapsed = time.perf_counter() - started
    vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
    rows: list[tuple[str, float, bool]] = []
    for index, case in enumerate(cases):
        similarity = _cosine(vectors[index * 2], vectors[index * 2 + 1])
        rows.append((case["id"], similarity, _passed(similarity, case["expected"])))

    input_tokens = int(response.usage.total_tokens)
    cost = input_tokens * args.input_cost_per_million / 1_000_000
    passed_count = sum(int(passed) for _, _, passed in rows)
    now = datetime.now(UTC)
    result_dir = ROOT / "results"
    result_dir.mkdir(exist_ok=True)
    result_path = result_dir / f"{now.date().isoformat()}_{args.model}.md"
    lines = [
        "# Wiki Embedding Batch Benchmark",
        "",
        f"- 실행 날짜: {now.isoformat()}",
        f"- 모델·차원: {args.model} / {args.dimensions}",
        f"- 구현 버전: {_revision()}",
        f"- 케이스: {len(rows)} / 성공: {passed_count}",
        f"- 정확도: {passed_count / len(rows):.2%}",
        f"- 평균 지연시간: {elapsed / len(rows):.3f}s",
        f"- 입력 토큰: {input_tokens}",
        f"- 예상 비용: ${cost:.6f}",
        "",
        "| ID | Cosine | 결과 |",
        "|---|---:|---:|",
    ]
    lines.extend(
        f"| {case_id} | {similarity:.4f} | {'PASS' if passed else 'FAIL'} |"
        for case_id, similarity, passed in rows
    )
    result_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(result_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
