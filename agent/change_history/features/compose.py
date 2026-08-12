"""종합 요약·타임라인 생성 워커(Compose worker, LLM 1콜).

Diff 결과의 팩트 **전체**(신규·갱신·유지)를 받아 Overview와 타임라인을 한 번에
생성한다. 유지(중복) 팩트도 넘기는 이유는, 이 보고서가 "달라진 것만" 보는 게
아니라 지금 상황 전체를 요약하는 정보요약보고서이기 때문이다 — 달라진 점은
별도 섹션(assembly.py)이 다루므로 여기 overview는 전체 그림을 그린다.
둘을 별도 호출로 쪼개지 않는 이유는 같은 팩트셋의 다른 뷰라서다 — 나눠 부르면
같은 사실을 두 섹션이 각자 서술해 중복이 생긴다.

원시 수집 문서는 넣지 않는다. 팩트에 딸린 참조 ID(P1·G2·L3)를 그대로 물려주고,
서술할 때 그 마커를 붙이게 한다. **인용 마커는 서식이 아니라 뒤에 오는
review(Critic) 검증이 실제로 작동하기 위한 필수 조건**이다 — Critic은 마커를
찾아 `get_source`로 원문과 대조하는 방식으로만 검증하므로, 마커가 없으면
대조할 대상이 없어 빈 검토를 통과시킨다.
"""

from __future__ import annotations

import json
import logging
from asyncio import to_thread
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from functools import partial

from agent.llm.api import complete_with_usage, strip_json_fence
from shared.change_history_models import DUPLICATE, UPDATED

from .dates import DATE_RULES_PROMPT
from .diff import DiffFact

logger = logging.getLogger("agent.change_history.compose")

_BASE_CONTEXT_CHARS = 2000

SYSTEM_PROMPT = (
    "너는 오늘의 정보를 정리해 요약 보고서를 쓰는 작성자다.\n"
    "\n"
    "주어지는 팩트는 세 종류로 표시돼 있다.\n"
    "- [신규] 오늘 처음 확인된 사실\n"
    "- [갱신] 예전과 값이 달라진 사실\n"
    "- [유지] 예전과 값이 같은, 안정적인 사실(오늘 새로 일어난 일이 아니다)\n"
    "\n"
    "세 가지를 한 번에 만든다.\n"
    "1. summary — 이번 보고서에서 가장 중요한 변화나 결론을 압축한 **한 문장**.\n"
    "   두세 문장짜리 요약이 아니라, 표제처럼 읽히는 한 문장 결론이다.\n"
    "   예: 'B사 HBM4 양산이 한 분기 밀리며 공급망 불확실성이 커지고 있습니다'\n"
    "   [갱신]·[신규]가 하나도 없으면(전부 [유지]) 오늘 상태를 있는 그대로 요약한다.\n"
    "2. overview — [신규]·[갱신]·[유지] 팩트 전체를 임의로 축약하거나 생략하지 말고\n"
    "   토글 OFF 일 때와 같은 생략 없는 풍부하고 완성도 높은 보고서 본문으로 작성한다.\n"
    "   **[유지] 팩트도 배경 설명으로 풍부하게 포함해 전체 상황을 설명해라.**\n"
    "   **팩트 한 줄을 그대로 옮겨 적지 마라.** 주어진 정보(오늘 값·이전 값·시점\n"
    "   표현)를 근거로 왜 그런지, 무엇이 달라졌는지, 그게 어떤 맥락에서 나온\n"
    "   변화인지 풀어서 문장으로 설명해라. 팩트 하나당 최소 두 문장 이상으로\n"
    "   써라 — 다만 주어진 정보에 없는 숫자·이름·사건은 새로 짓지 마라.\n"
    "   **문장마다 줄을 바꾸지 마라.** 관련된 문장은 하나의 문단으로 자연스럽게\n"
    "   이어 써라 — 문장 하나씩 뚝뚝 끊어 놓으면 글이 아니라 메모처럼 읽힌다.\n"
    "   다루는 대상·주제가 바뀔 때만 빈 줄로 문단을 나눠라.\n"
    "3. timeline — **[신규]·[갱신] 팩트에 한해서만** 언제의 일인지 절대 날짜로\n"
    "   정리한 항목들. [유지] 팩트는 오늘 새로 일어난 사건이 아니므로 타임라인에\n"
    "   넣지 않는다.\n"
    "\n"
    "인용 규칙(가장 중요하다. 어기면 결과 전체를 다시 쓰게 된다):\n"
    "- **overview의 모든 문단에 참조 ID가 최소 하나씩** 있어야 한다.\n"
    "  참조 ID가 하나도 없는 문단은 규칙 위반이다.\n"
    "- 팩트에서 가져온 내용을 서술할 때마다 그 팩트의 참조 ID를 대괄호로 붙인다.\n"
    "- 참조 ID는 주어진 팩트 목록에 있는 것만 쓴다. 없는 ID를 만들지 않는다.\n"
    "- 이 마커가 없으면 뒤에 오는 검증 단계가 사실 확인을 하지 못한다.\n"
    "\n"
    "overview 예시(이 형태를 따른다):\n"
    "  B사는 여전히 HBM4를 주력 제품으로 개발 중이며 [P1], 지난 보고서에서\n"
    "  2026년 2분기로 잡혀 있던 양산 시점이 이번에 3분기로 밀렸습니다 [G1].\n"
    "  같은 기간 C사는 품질 인증을 처음 통과해 공급자가 늘어날 여지가 생겼습니다 [G2].\n"
    "\n"
    "문체 규칙:\n"
    "- 존댓말로, 읽는 사람을 배려하는 친절한 어투로 쓴다('~습니다').\n"
    "- 이모지나 장식 기호를 쓰지 않는다.\n"
    "- 과장된 감탄이나 광고성 표현 없이 담백하게 서술한다.\n"
    "\n"
    + DATE_RULES_PROMPT
    + "\n"
    "JSON 객체 하나로만 답한다.\n"
    '{"title":"보고서 제목","summary":"한 문장 결론",'
    '"overview":"종합 요약 markdown",'
    '"timeline":[{"fact_index":0,"date":"YYYY-MM-DD 또는 빈 문자열",'
    '"precision":"day|month|quarter|half|year|unknown",'
    '"description":"그 시점에 무슨 일이 있었는지 한 줄 [G2]"}]}\n'
)

# Diff worker의 verdict 값을 사람이 읽는 한국어 라벨로 바꾼다. describe_facts_for_writing과
# assembly.py의 팩트 나열이 같은 라벨을 쓴다.
_VERDICT_LABELS = {UPDATED: "갱신", DUPLICATE: "유지"}


@dataclass(frozen=True, slots=True)
class TimelineDraft:
    """Compose worker가 만든 타임라인 항목 초안 (검증 전).

    Attributes:
        fact_index: 이 항목이 근거로 삼은 팩트의 순번. 검증에서 실제 팩트와
            연결하고, 드롭할 때 어느 팩트가 문제였는지 특정하는 데 쓴다.
    """

    fact_index: int
    raw_date: str
    precision: str
    description: str


@dataclass(frozen=True, slots=True)
class ComposeOutcome:
    """Overview·타임라인 생성 결과."""

    title: str = ""
    summary: str = ""
    overview: str = ""
    timeline: tuple[TimelineDraft, ...] = ()
    failed: bool = False
    input_tokens: int = 0
    output_tokens: int = 0


def describe_facts_for_writing(facts: Sequence[DiffFact]) -> str:
    """워커에게 넘길 팩트 목록을 문자열로 만든다.

    참조 ID를 각 줄에 붙여, 서술할 때 그대로 인용 마커로 쓰게 한다. 갱신 팩트도
    **오늘 값만** 준다 — before 값은 조립 단계가 DB에서 읽어 붙이므로 워커가
    과거값을 지어낼 여지를 두지 않는다.

    verdict를 [신규]/[갱신]/[유지] 라벨로 붙여, 워커가 무엇이 실제로 달라진
    것이고 무엇이 배경 설명용 안정적 사실인지 구분하게 한다.
    """
    lines: list[str] = []
    for index, fact in enumerate(facts):
        marker = f" [{fact.source_reference}]" if fact.source_reference else ""
        label = _VERDICT_LABELS.get(fact.verdict, "신규")
        when = f" (자료 속 시점 표현: {fact.date_expression})" if fact.date_expression else ""
        lines.append(
            f"{index}. [{label}] {fact.subject} / {fact.attribute} = "
            f"{fact.fact_value or '(값 없음)'}{when}\n"
            f"   {fact.today_statement}{marker}"
        )
    return "\n".join(lines)


def parse_compose_response(text: str) -> ComposeOutcome | None:
    """Compose worker의 JSON 응답을 결과 구조로 변환한다. 형식이 어긋나면 None."""
    try:
        payload = json.loads(strip_json_fence(text))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    overview = str(payload.get("overview") or "").strip()
    if not overview:
        return None
    entries: list[TimelineDraft] = []
    raw_timeline = payload.get("timeline")
    if isinstance(raw_timeline, list):
        for item in raw_timeline:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description") or "").strip()
            if not description:
                continue
            try:
                fact_index = int(item.get("fact_index"))
            except (TypeError, ValueError):
                fact_index = -1
            entries.append(
                TimelineDraft(
                    fact_index=fact_index,
                    raw_date=str(item.get("date") or "").strip(),
                    precision=str(item.get("precision") or "unknown").strip(),
                    description=description,
                )
            )
    return ComposeOutcome(
        title=str(payload.get("title") or "").strip(),
        summary=str(payload.get("summary") or "").strip(),
        overview=overview,
        timeline=tuple(entries),
    )


def compose_overview_and_timeline(
    *,
    topic: str,
    facts: Sequence[DiffFact],
    reference_date: date,
    base_summary: str = "",
    model: str = "gpt-4.1-mini",
    correction: str = "",
) -> ComposeOutcome:
    """오늘 확인된 팩트 전체로 종합 요약과 타임라인을 한 번의 호출로 생성한다.

    Args:
        topic: 보고서 주제
        facts: 오늘 확인된 팩트 전체(신규·갱신·유지). 유지 팩트도 넣어야
            overview가 "지금 전체 그림"을 그릴 수 있다.
        reference_date: 상대 날짜 표현을 환산할 기준일. 하드코딩하지 않고
            실행 시 주입받아 테스트가 "오늘"에 흔들리지 않게 한다.
        base_summary: 직전 보고서의 맥락 요약. 첫 실행이면 빈 문자열
        model: 사용할 모델
        correction: 재작업 시 앞에 붙일 교정 지시

    Returns:
        생성 결과. 호출·해석에 실패하면 failed=True인 빈 결과(호출자가 재작업 판단).
    """
    if not facts:
        return ComposeOutcome(failed=True)
    # 첫 실행이어도 "이전과 비교할 자료가 없다"는 식의 메타 발언은 요청하지
    # 않는다 — 독자에게는 그냥 오늘의 정리된 보고서일 뿐이라, 그 코멘트가 오히려
    # 어색하고 불친절하게 읽힌다(2026-08-12 사용자 피드백).
    base_block = (
        f"직전 보고서 맥락(참고용, 인용하지 마라):\n{base_summary[:_BASE_CONTEXT_CHARS]}\n\n"
        if base_summary.strip()
        else ""
    )
    correction_block = f"[재작업 지시] {correction}\n\n" if correction else ""
    user_prompt = (
        f"주제: {topic}\n"
        f"기준일: {reference_date.isoformat()}\n\n"
        + correction_block
        + base_block
        + "오늘 확인된 팩트:\n"
        + describe_facts_for_writing(facts)
    )
    try:
        completion = complete_with_usage(SYSTEM_PROMPT, user_prompt, model=model)
    except Exception:
        logger.exception("Compose worker 호출에 실패했습니다.")
        return ComposeOutcome(failed=True)

    parsed = parse_compose_response(completion.text)
    if parsed is None:
        logger.warning(
            "Compose worker 응답을 해석하지 못했습니다: %s", completion.text[:200]
        )
        return ComposeOutcome(
            failed=True,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
        )
    logger.info(
        "Overview·타임라인 생성 완료: topic=%s 타임라인 %d건", topic, len(parsed.timeline)
    )
    return ComposeOutcome(
        title=parsed.title,
        summary=parsed.summary,
        overview=parsed.overview,
        timeline=parsed.timeline,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def chg_003(
    *,
    topic: str,
    facts: Sequence[DiffFact],
    reference_date: date,
    base_summary: str = "",
    model: str = "gpt-4.1-mini",
    correction: str = "",
) -> ComposeOutcome:
    """[CHG-003] 종합 요약·타임라인 생성.

    오늘 확인된 팩트 전체(신규·갱신·유지)로 Overview와 타임라인을 한 번의 LLM
    호출로 만든다. 동기 호출이라 Transaction·이벤트 루프를 막지 않도록
    스레드에서 실행한다.
    """
    return await to_thread(
        partial(
            compose_overview_and_timeline,
            topic=topic,
            facts=facts,
            reference_date=reference_date,
            base_summary=base_summary,
            model=model,
            correction=correction,
        )
    )
