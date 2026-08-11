"""주제 목록(topics) 리포트가 주제마다 섹션을 제대로 나누는지 실제 LLM으로 평가한다.

사용자가 관심사 키워드를 여러 개 고르면 한 리포트가 주제마다 별도 섹션을 써야
한다. 이 벤치마크는 생성 프롬프트 단계만 측정한다 — 근거 문서를 데이터셋에서
그대로 주입하므로 수집·풀 검색·선별 경로는 지나지 않는다.

측정 항목은 넷이다.

    주제 커버리지  : 주제마다 그 주제의 근거가 실제로 인용됐는가
                     (섹션 제목 문자열이 아니라 인용으로 판정한다 — 제목 표현은
                      LLM이 바꿔 쓰므로 문자열 매칭은 신뢰할 수 없다)
    섹션 분할      : 본문이 주제 수만큼 섹션으로 나뉘었는가
    교차 오염      : 한 섹션이 다른 주제의 근거를 섞어 인용했는가
    근거 절단      : 프롬프트 근거 상한에 걸려 뒤쪽 주제 근거가 잘렸는가

비용이 발생하므로 예상 입력 Token을 먼저 표시하고 --confirm-cost를 명시한
경우에만 실행한다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
PROJECT_ROOT = ROOT.parents[1]

# OPENAI_API_KEY를 .env에서 읽는다(다른 벤치마크와 같은 방식). import보다 먼저
# 호출해야 모듈 로딩 시점에 클라이언트를 만드는 경로에서도 키가 보인다.
load_dotenv(PROJECT_ROOT / ".env")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.report_builder.api import ReportContextDocument, generate_report_content  # noqa: E402

DATASET = ROOT / "dataset.jsonl"
LAST_RUN = ROOT / "last_run.json"

# agent/report_builder/features/generation.py의 _MAX_CONTEXT_CHARS를 그대로 옮긴
# 값이다. 그쪽이 바뀌면 이 값도 따라 바꿔야 한다 — 절단 추정에만 쓰고 생성
# 자체에는 영향을 주지 않으므로, 어긋나도 결과가 조용히 틀리지는 않는다.
_MAX_CONTEXT_CHARS = 16000

# 본문에서 [G1] 형태의 인용 마커를 찾는다.
_CITATION_PATTERN = re.compile(r"\[([A-Z]\d+)\]")
# Markdown 제목 줄(#, ##, ### …)을 섹션 경계로 본다.
_HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.*)$")


def load_cases() -> list[dict[str, object]]:
    """JSONL 벤치마크 데이터셋을 순서대로 읽는다."""
    return [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def expand_content(entry: dict[str, object]) -> str:
    """근거 본문을 만든다. repeat가 있으면 그 횟수만큼 이어 붙여 긴 문서를 흉내낸다.

    절단 케이스를 데이터셋에 수만 자로 적어 두면 파일을 읽을 수 없으므로,
    반복 횟수로 길이를 표현한다.
    """
    content = str(entry["content"])
    repeat = int(entry.get("repeat", 1) or 1)
    return " ".join([content] * repeat)


def build_contexts(case: dict[str, object]) -> list[ReportContextDocument]:
    """데이터셋 케이스의 근거 목록을 생성 함수가 받는 Context 문서로 바꾼다."""
    contexts: list[ReportContextDocument] = []
    for entry in case["contexts"]:  # type: ignore[index]
        reference = str(entry["reference"])
        contexts.append(
            ReportContextDocument(
                reference=reference,
                document_version_id=f"version-{reference}",
                chunk_id=f"chunk-{reference}",
                namespace_key="global",
                title=str(entry["title"]),
                content=expand_content(entry),
                url=f"https://example.com/{reference.lower()}",
                score=1.0,
            )
        )
    return contexts


def estimate_included_references(contexts: list[ReportContextDocument]) -> list[str]:
    """근거 상한에 걸리기 전까지 프롬프트에 실제로 담기는 근거를 추정한다.

    generation.py는 블록 하나가 상한을 넘기면 그 블록만 건너뛰고 더 작은 뒤쪽
    블록은 계속 시도한다(continue). 이 함수도 같은 규칙으로 재현해야 어느
    주제가 실제로 근거를 잃는지 정확히 잡아낸다.
    """
    included: list[str] = []
    current_size = 0
    for context in contexts:
        block = (
            f"[{context.reference}] {context.title}\n"
            f"URL: {context.url or '(개인 Wiki)'}\n"
            f"내용:\n{context.content.strip()}"
        )
        if included and current_size + len(block) > _MAX_CONTEXT_CHARS:
            continue
        included.append(context.reference)
        current_size += len(block)
    return included


def _normalize(text: str) -> str:
    """제목 대조용으로 공백과 대소문자 차이를 지운다."""
    return "".join(text.split()).casefold()


def split_sections(body: str) -> list[tuple[str, str]]:
    """본문을 Markdown 제목 기준으로 (제목, 내용) 섹션 목록으로 나눈다.

    제목이 하나도 없으면 본문 전체를 제목 없는 섹션 하나로 본다.
    """
    sections: list[tuple[str, str]] = []
    heading = ""
    buffer: list[str] = []
    for line in body.splitlines():
        matched = _HEADING_PATTERN.match(line.strip())
        if matched:
            if heading or buffer:
                sections.append((heading, "\n".join(buffer)))
            heading = matched.group(1).strip()
            buffer = []
        else:
            buffer.append(line)
    if heading or buffer:
        sections.append((heading, "\n".join(buffer)))
    return sections


def evaluate(case: dict[str, object], body: str, included: list[str]) -> dict[str, object]:
    """생성된 본문이 주제마다 섹션과 인용을 갖췄는지 채점한다.

    Args:
        case: 데이터셋 케이스
        body: 생성된 본문 Markdown
        included: 근거 상한을 넘기 전 프롬프트에 담긴 근거 목록

    Returns:
        주제 커버리지·교차 오염·절단 지표를 담은 채점 결과
    """
    topics = [str(topic) for topic in (case.get("topics") or [])] or [str(case["topic"])]
    owner_of = {
        str(entry["reference"]): str(entry["topic"])
        for entry in case["contexts"]  # type: ignore[index]
    }
    included_set = set(included)

    # 절단으로 근거를 통째로 잃은 주제. 이 주제는 인용이 없어도 LLM 탓이 아니다.
    starved = [
        topic
        for topic in topics
        if not any(owner == topic and ref in included_set for ref, owner in owner_of.items())
    ]

    cited_topics: set[str] = set()
    cross_contaminated: list[str] = []
    for heading, content in split_sections(body):
        refs = set(_CITATION_PATTERN.findall(content))
        owners = {owner_of[ref] for ref in refs if ref in owner_of}
        cited_topics |= owners
        if len(owners) > 1:
            cross_contaminated.append(heading or "(제목 없음)")

    expected = [topic for topic in topics if topic not in starved]
    missing = [topic for topic in expected if topic not in cited_topics]

    # 근거가 한 건도 없는 주제인데 섹션을 쓴 경우. 2026-08-11 실측에서 '김건희'
    # 섹션이 인용 없이 "검사님, 다른 영부인 수사 다 해봤느냐"까지 따옴표로
    # 인용해 나왔다. 근거가 없으면 섹션이 아예 없어야 한다.
    headings = [heading for heading, _ in split_sections(body) if heading]
    fabricated = [
        topic
        for topic in starved
        if any(_normalize(topic) in _normalize(heading) for heading in headings)
    ]
    # 제목이 붙은 섹션인데 인용이 하나도 없는 경우. 해석 단락(규칙 6)은 참조를
    # 붙이지 않는 것이 정상이라 주제 이름을 가진 섹션만 본다.
    uncited = [
        heading
        for heading, content in split_sections(body)
        if heading
        and any(_normalize(topic) in _normalize(heading) for topic in topics)
        and not _CITATION_PATTERN.findall(content)
    ]
    # 근거 문서에 실려 있지만 주제와 무관한 사실이 본문에 옮겨졌는가(규칙 5).
    # 데이터셋이 그 사실만 가리키는 문구를 지정한다.
    leaked = [
        phrase
        for phrase in (case.get("forbidden_phrases") or [])  # type: ignore[union-attr]
        if str(phrase) in body
    ]
    # 채점을 두 갈래로 나눈다. 근거가 잘려 사라진 주제를 LLM 탓으로 돌리면
    # 프롬프트 품질과 파이프라인 결함이 한 숫자에 섞여 원인을 못 가린다.
    #   llm_passed    : 받은 근거 안에서 주제를 빠뜨리거나 섞지 않았는가
    #   system_passed : 사용자가 고른 주제가 결국 다 리포트에 실렸는가
    llm_passed = (
        not missing
        and not cross_contaminated
        and not fabricated
        and not uncited
        and not leaked
    )
    return {
        "topics": len(topics),
        "covered": len(expected) - len(missing),
        "expected": len(expected),
        "missing_topics": missing,
        "cross_contaminated_sections": cross_contaminated,
        "fabricated_sections": fabricated,
        "uncited_sections": uncited,
        "leaked_offtopic_phrases": leaked,
        "starved_topics": starved,
        "dropped_references": [
            ref for ref in owner_of if ref not in included_set
        ],
        "sections": sum(1 for heading, _ in split_sections(body) if heading),
        "llm_passed": llm_passed,
        "system_passed": llm_passed and not starved,
    }


def estimate_input_tokens(cases: list[dict[str, object]]) -> int:
    """문자수 4자당 1 Token 가정으로 대략적인 입력량을 계산한다."""
    characters = 0
    for case in cases:
        characters += len(str(case["topic"]))
        characters += sum(len(str(topic)) for topic in (case.get("topics") or []))
        for entry in case["contexts"]:  # type: ignore[index]
            characters += len(expand_content(entry)) + len(str(entry["title"]))
    return max(1, characters // 4)


def main() -> int:
    """비용 확인 후 전체 벤치마크를 실행하고 집계 결과를 출력한다."""
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--confirm-cost", action="store_true")
    parser.add_argument("--case", default="", help="특정 케이스 id만 실행")
    args = parser.parse_args()

    cases = load_cases()
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]
        if not cases:
            print(f"케이스를 찾지 못했습니다: {args.case}")
            return 2
    estimated_tokens = estimate_input_tokens(cases)
    print(
        f"cases={len(cases)}, estimated_input_tokens={estimated_tokens}, "
        "output_tokens_estimate=6000"
    )
    if not args.confirm_cost:
        print("실제 호출을 실행하려면 --confirm-cost를 추가하세요.")
        return 2

    results: list[dict[str, object]] = []
    for case in cases:
        contexts = build_contexts(case)
        included = estimate_included_references(contexts)
        topics = [str(topic) for topic in (case.get("topics") or [])]
        started = time.perf_counter()
        generated = generate_report_content(
            topic=str(case["topic"]),
            topics=topics,
            content_type=str(case["content_type"]),
            language=str(case["language"]),
            contexts=contexts,
            model=args.model,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        scored = evaluate(case, generated.body, included)
        results.append(
            {
                "id": case["id"],
                "note": case.get("note", ""),
                "latency_ms": latency_ms,
                "title": generated.title,
                "citations": list(generated.citation_references),
                "body": generated.body,
                **scored,
            }
        )
        status = "PASS" if scored["llm_passed"] else "FAIL"
        starved = scored["starved_topics"]
        suffix = f" · 근거 절단으로 유실된 주제 {len(starved)}개" if starved else ""
        print(
            f"[{status}] {case['id']} — {scored['covered']}/{scored['expected']} 주제 인용, "
            f"{latency_ms}ms{suffix}"
        )

    LAST_RUN.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    llm_passed = sum(int(bool(result["llm_passed"])) for result in results)
    system_passed = sum(int(bool(result["system_passed"])) for result in results)
    total_latency = sum(int(result["latency_ms"]) for result in results)
    print(f"llm_passed={llm_passed}/{len(results)} (받은 근거 안에서의 생성 품질)")
    print(f"system_passed={system_passed}/{len(results)} (근거 절단까지 포함한 최종 결과)")
    print(f"model={args.model}, average_latency_ms={total_latency // max(1, len(results))}")
    print(f"상세 결과: {LAST_RUN}")
    return 0 if llm_passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
