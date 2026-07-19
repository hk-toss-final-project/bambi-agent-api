"""Bambi 개인·Global 근거 결합 생성 품질을 실제 LLM으로 평가한다.

비용이 발생하므로 예상 입력 Token과 비용을 먼저 표시하고 --confirm-cost를
명시한 경우에만 최소 10개 Benchmark 케이스를 실행한다.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from agent.bambi.api import BambiContextDocument, generate_bambi_content

ROOT = Path(__file__).parent
DATASET = ROOT / "dataset.jsonl"


def load_cases() -> list[dict[str, object]]:
    """JSONL Benchmark 데이터셋을 순서대로 읽는다."""
    return [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def estimate_input_tokens(cases: list[dict[str, object]]) -> int:
    """문자수 4자당 1 Token 가정으로 대략적인 입력량을 계산한다."""
    characters = sum(
        len(str(case.get(field, "")))
        for case in cases
        for field in ("topic", "personal", "global")
    )
    return max(1, characters // 4)


def main() -> int:
    """비용 확인 후 전체 Benchmark를 실행하고 JSON 결과를 출력한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--confirm-cost", action="store_true")
    args = parser.parse_args()
    cases = load_cases()
    estimated_tokens = estimate_input_tokens(cases)
    print(
        f"cases={len(cases)}, estimated_input_tokens={estimated_tokens}, "
        "output_tokens_estimate=5000"
    )
    if not args.confirm_cost:
        print("실제 호출을 실행하려면 --confirm-cost를 추가하세요.")
        return 2

    results: list[dict[str, object]] = []
    for case in cases:
        started = time.perf_counter()
        generated = generate_bambi_content(
            topic=str(case["topic"]),
            content_type=str(case["content_type"]),
            language=str(case["language"]),
            contexts=[
                BambiContextDocument(
                    reference="P1",
                    document_version_id="personal-version",
                    chunk_id="personal-chunk",
                    namespace_key="user/benchmark",
                    title="Personal Wiki",
                    content=str(case["personal"]),
                    url=None,
                    score=1,
                ),
                BambiContextDocument(
                    reference="G1",
                    document_version_id="global-version",
                    chunk_id="global-chunk",
                    namespace_key="global",
                    title="Latest Source",
                    content=str(case["global"]),
                    url="https://example.com/latest",
                    score=1,
                ),
            ],
            model=args.model,
        )
        required = set(case["required_refs"])
        actual = set(generated.citation_references)
        results.append(
            {
                "id": case["id"],
                "passed": required <= actual,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "citations": list(generated.citation_references),
                "title": generated.title,
            }
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    passed = sum(int(result["passed"]) for result in results)
    print(f"passed={passed}/{len(results)}, model={args.model}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
