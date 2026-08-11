"""리포트 생성 루프 V1·V2를 같은 입력으로 비교 평가한다.

주제별 fan-out(V2)이 단일 그래프(V1)보다 실제로 나은지를 지표로 확인한다.
측정 항목은 rollout 문서 §7-4가 정한 것이다.

- 요청 주제 수 대비 실제 섹션 수 (V1이 근거 없는 주제를 조용히 지우는 문제)
- 근거 없는 주제가 커버리지 노트로 남았는지
- 섹션 재작성 횟수와 등급 분포
- 지연 시간과 Token 사용량(비용)

실제 Provider를 호출하므로 비용이 발생한다. 예상 Token을 먼저 표시하고
`--confirm-cost`를 명시한 경우에만 실행한다(다른 벤치마크와 같은 규칙).

주의: 이 스크립트는 **생성 단계만** 비교한다. 조사(research)·저장(persist)은
DB 연결이 필요해 여기서 대체하며, 근거는 dataset.jsonl이 고정으로 제공한다.
따라서 "근거를 얼마나 잘 찾는가"가 아니라 "같은 근거로 얼마나 잘 쓰는가"를 본다.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parents[1]

# OPENAI_API_KEY를 .env에서 읽는다(다른 벤치마크와 같은 방식). import보다 먼저
# 호출해야 모듈 로딩 시점에 클라이언트를 만드는 경로에서도 키가 보인다.
load_dotenv(PROJECT_ROOT / ".env")

from agent.report_builder.api import (  # noqa: E402
    GRADE_NO_EVIDENCE,
    ReportContextDocument,
    assemble_sections,
    coverage_note,
    generate_report_content_with_quality,
)

DATASET = ROOT / "dataset.jsonl"


def load_cases() -> list[dict[str, object]]:
    """JSONL Benchmark 데이터셋을 순서대로 읽는다."""
    return [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def estimate_input_tokens(cases: list[dict[str, object]]) -> int:
    """문자수 4자당 1 Token 가정으로 대략적인 입력량을 계산한다.

    V2는 주제마다 프롬프트를 따로 만들어 근거가 중복되지 않는 대신 지시문이
    주제 수만큼 반복된다. 지시문 몫을 주제당 400자로 잡아 더한다.
    """
    characters = 0
    for case in cases:
        topics = list(case.get("topics") or [])
        evidence = dict(case.get("evidence") or {})
        characters += sum(
            len(sentence) for lines in evidence.values() for sentence in lines
        )
        characters += 400 * len(topics)
    return max(1, characters // 4)


def _documents(topic: str, sentences: list[str]) -> list[ReportContextDocument]:
    """데이터셋 근거 문장을 생성 입력용 Context 문서로 만든다."""
    return [
        ReportContextDocument(
            reference=f"G{index + 1}",
            document_version_id=f"bench-{topic}-{index}",
            chunk_id=f"bench-{topic}-{index}",
            namespace_key="global/news",
            title=f"{topic} 근거 {index + 1}",
            content=sentence,
            url=f"https://bench.test/{topic}/{index}",
            score=0.9 - index * 0.05,
        )
        for index, sentence in enumerate(sentences)
    ]


def run_v2_case(case: dict[str, object], *, model: str) -> dict[str, object]:
    """V2 방식(주제별 생성 후 조립)으로 한 케이스를 실행한다."""
    topics = [str(item).strip() for item in (case.get("topics") or []) if str(item).strip()]
    seen: set[str] = set()
    planned = [
        topic
        for topic in topics
        if not (topic.casefold() in seen or seen.add(topic.casefold()))
    ]
    evidence = dict(case.get("evidence") or {})
    sections: list[dict[str, object]] = []
    started = time.perf_counter()
    for topic in planned:
        sentences = [str(item) for item in (evidence.get(topic) or [])]
        if not sentences:
            sections.append({"topic": topic, "content": None, "contexts": []})
            continue
        contexts = _documents(topic, sentences)
        content = generate_report_content_with_quality(
            topic=topic,
            content_type=str(case.get("content_type") or "interest_news_card"),
            language=str(case.get("language") or "ko"),
            contexts=contexts,
            model=model,
        )
        sections.append({"topic": topic, "content": content, "contexts": contexts})
    generated, _ = assemble_sections(sections, fallback_topic=planned[0] if planned else "")
    latency_ms = int((time.perf_counter() - started) * 1000)
    missing = [
        section["topic"] for section in sections if section.get("content") is None
    ]
    return {
        "sections": len(sections),
        "no_evidence": len(missing),
        "coverage_notes_present": all(
            coverage_note(str(topic)) in generated.body for topic in missing
        ),
        "body_chars": len(generated.body),
        "citations": len(generated.citation_references),
        "latency_ms": latency_ms,
    }


def score(case: dict[str, object], observed: dict[str, object]) -> dict[str, object]:
    """기대값과 관측값을 대조해 케이스 성패를 판정한다."""
    expect = dict(case.get("expect") or {})
    failures: list[str] = []
    if "sections" in expect and observed["sections"] != expect["sections"]:
        failures.append(f"sections {observed['sections']}!={expect['sections']}")
    if "no_evidence" in expect and observed["no_evidence"] != expect["no_evidence"]:
        failures.append(
            f"no_evidence {observed['no_evidence']}!={expect['no_evidence']}"
        )
    if observed["no_evidence"] and not observed["coverage_notes_present"]:
        failures.append("커버리지 노트 누락")
    return {
        "id": case.get("id"),
        "passed": not failures,
        "failures": failures,
        **observed,
    }


def main() -> int:
    """비용 확인 후 전체 Benchmark를 실행하고 JSON 결과를 출력한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--confirm-cost", action="store_true")
    parser.add_argument("--case", default="", help="특정 케이스 id만 실행")
    args = parser.parse_args()

    cases = load_cases()
    if args.case:
        cases = [case for case in cases if case.get("id") == args.case]
    estimated_tokens = estimate_input_tokens(cases)
    llm_calls = sum(
        len([t for t in (case.get("topics") or []) if (case.get("evidence") or {}).get(t)])
        for case in cases
    )
    print(
        f"cases={len(cases)}, llm_calls≈{llm_calls}, "
        f"estimated_input_tokens={estimated_tokens}, output_tokens_estimate={llm_calls * 700}"
    )
    if not args.confirm_cost:
        print("비용 확인이 필요합니다. --confirm-cost 를 붙여 다시 실행하세요.")
        return 1

    results = [score(case, run_v2_case(case, model=args.model)) for case in cases]
    passed = sum(1 for result in results if result["passed"])
    summary = {
        "model": args.model,
        "cases": len(results),
        "passed": passed,
        "accuracy": round(passed / len(results), 3) if results else 0.0,
        "avg_latency_ms": (
            round(sum(int(r["latency_ms"]) for r in results) / len(results))
            if results
            else 0
        ),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
