"""팩트 추출·과거 대조 워커(Diff worker).

이 설계에서 **유일하게 도구를 쥔 자율 에이전트**다. 오늘 수집된 원본 문서를
받아 팩트 단위를 추출하면서, 각 팩트마다 과거 조회가 필요한지 스스로 판단해
`search_base_facts`를 부른다. 추출과 매칭을 두 단계로 쪼개지 않는 이유는,
"이게 어제 그 얘기인가"를 판단하려면 팩트를 뽑는 순간의 맥락이 필요해서다.

**팩트 하나 = (subject, attribute, fact_value)**. 중복·갱신 판정은
(subject, attribute) 매칭으로 하고 값이 다르면 갱신이다.

**before 문구를 LLM이 쓰지 않는다.** 갱신일 때 과거 팩트의 ID만 찍게 하고,
before 텍스트는 검증 단계가 그 ID로 DB에서 읽어 온다. 도구는 읽기 전용이며
델타 테이블 안에서만 조회한다 — 웹 검색·외부 수집·쓰기는 없다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection

from agent.llm.api import ToolCallRecord, ToolSpec, run_tool_loop, strip_json_fence
from infrastructure.persistence.api import (
    search_change_history_facts,
    set_personal_wiki_scope,
)
from shared.change_history_models import DUPLICATE, NEW, UPDATED, ChangeHistoryFact
from shared.report_models import ReportContextDocument

logger = logging.getLogger("agent.change_history.diff")

type DictRow = dict[str, Any]

DIFF_MAX_ITERATIONS = 6
_CONTEXT_SNIPPET_CHARS = 1200
_MAX_CONTEXT_CHARS = 14000
_VERDICTS = {NEW, UPDATED, DUPLICATE}

SYSTEM_PROMPT = (
    "너는 오늘 수집한 자료에서 사실(팩트)을 뽑아, 과거에 이미 알던 것과\n"
    "무엇이 달라졌는지 가려내는 분석가다.\n"
    "\n"
    "팩트 하나는 세 요소다.\n"
    "- subject: 사실의 주체 (기업·제품·인물·정책 등 고유한 대상)\n"
    "- attribute: 그 주체의 어떤 속성/사건인가 (양산 일정, 가격, 점유율, 규제 등)\n"
    "- fact_value: 오늘 자료가 말하는 값·상태\n"
    "\n"
    "**attribute에는 값을 넣지 마라.** attribute는 날이 바뀌어도 그대로인 이름표여야\n"
    "하고, 바뀌는 값은 전부 fact_value로 간다. 이게 어긋나면 내일 같은 사실을\n"
    "찾지 못해 갱신을 놓친다.\n"
    "  맞는 예: subject='코스닥', attribute='등락률', fact_value='3거래일 만에 21% 급등'\n"
    "  틀린 예: subject='코스닥', attribute='3거래일 만에 21% 급등'  ← 값이 이름표에 섞였다\n"
    "\n"
    "도구:\n"
    "- search_base_facts(query): 이 주제로 과거에 저장해 둔 팩트를 찾는다.\n"
    "  팩트를 하나 뽑을 때마다 '이건 예전에도 있었나'가 궁금하면 부른다.\n"
    "\n"
    "판정 규칙:\n"
    "1. 과거에 같은 (subject, attribute)가 없으면 new.\n"
    "2. 있는데 값이 달라졌으면 updated. 이때 updates_fact_id에 그 과거 팩트의\n"
    "   ID를 **그대로** 적는다. 과거 값을 문장으로 다시 쓰지 마라 — ID만 필요하다.\n"
    "3. 있고 값도 같으면 duplicate. **값이 같은지도 글자가 아니라 실질로\n"
    "   판단한다** — '다음 달부터 시행'과 '다음 달 초부터 적용'은 표현만 다를\n"
    "   뿐 같은 시점을 가리키므로 duplicate다. 새로 들어온 자료가 어제 사실을\n"
    "   다른 말로 재확인·재보도한 것뿐이면 duplicate이지 updated가 아니다.\n"
    "   실질 값이 실제로 달라졌을 때만(수치·날짜·상태가 바뀜) updated다.\n"
    "   duplicate는 보고서에 쓰지 않는다.\n"
    "4. **속성 이름도 표현이 아니라 뜻으로 맞춰라.** 같은 주체의 같은 성질을\n"
    "   가리키면 단어가 달라도 같은 attribute다 — '급등률'과 '등락률', '양산\n"
    "   일정'과 '생산 개시 시점'은 같은 것으로 본다. 이때 새 표현을 만들지 말고\n"
    "   **과거 팩트에 적힌 attribute를 그대로 재사용**해라. 표기가 날마다\n"
    "   흔들리면 같은 사실이 매번 신규로 쌓인다.\n"
    "5. 확실하지 않으면 new로 두지 말고 도구로 먼저 확인한다.\n"
    "6. 자료에 없는 사실을 지어내지 않는다.\n"
    "7. **date_expression은 사건 자체의 시점이지, 이 소식이 보도된 시점이\n"
    "   아니다.** '정부가 오늘 발표했다'는 발표 행위의 시점일 뿐 사건(양산·\n"
    "   시행·검토)이 언제 일어나는지는 알려주지 않는다. 자료가 사건 자체의\n"
    "   시점을 명시하지 않으면(예: '조만간', '추후', 시점 언급 없음)\n"
    "   date_expression은 반드시 빈 문자열이다. **'오늘'을 기본값으로 채우지\n"
    "   마라** — 자료 문장에 사건의 시점으로서 '오늘'이 실제로 쓰였을 때만 쓴다.\n"
    "\n"
    "확인이 끝나면 JSON 객체 하나로만 답한다.\n"
    '{"facts":[{"verdict":"new|updated|duplicate",'
    '"updates_fact_id":"갱신일 때 과거 팩트 ID, 아니면 null",'
    '"subject":"...","attribute":"...","fact_value":"...",'
    '"today_statement":"오늘의 사실을 한 문장으로",'
    '"date_expression":"사건 자체의 시점 표현만(보도 시점 아님), 없으면 빈 문자열",'
    '"source_reference":"근거 참조 ID (예: P1, G2, L3)"}]}\n'
)

# 첫 실행(Base 없음)에는 과거 대조 지시를 빼고 같은 출력 형식만 요구한다.
# Diff worker 자체를 건너뛰지 않는 이유는, 구조화 출력 형식이 그대로 유지돼야
# Compose 입력과 델타 테이블 저장에 똑같이 쓸 수 있기 때문이다.
FIRST_RUN_SYSTEM_PROMPT = (
    "너는 오늘 수집한 자료에서 사실(팩트)을 뽑는 분석가다.\n"
    "이 주제는 이번이 첫 실행이라 비교할 과거 기록이 없다.\n"
    "\n"
    "팩트 하나는 세 요소다.\n"
    "- subject: 사실의 주체 (기업·제품·인물·정책 등 고유한 대상)\n"
    "- attribute: 그 주체의 어떤 속성/사건인가 (양산 일정, 가격, 점유율, 규제 등)\n"
    "- fact_value: 오늘 자료가 말하는 값·상태\n"
    "\n"
    "**attribute에는 값을 넣지 마라.** attribute는 날이 바뀌어도 그대로인 이름표여야\n"
    "하고, 바뀌는 값은 전부 fact_value로 간다. 내일 이 팩트와 대조해 갱신을\n"
    "찾아내려면 이름표가 안정적이어야 한다.\n"
    "  맞는 예: subject='코스닥', attribute='등락률', fact_value='3거래일 만에 21% 급등'\n"
    "  틀린 예: subject='코스닥', attribute='3거래일 만에 21% 급등'  ← 값이 이름표에 섞였다\n"
    "\n"
    "모든 팩트의 verdict는 new이고 updates_fact_id는 null이다.\n"
    "자료에 없는 사실을 지어내지 않는다.\n"
    "\n"
    "**date_expression은 사건 자체의 시점이지, 이 소식이 보도된 시점이 아니다.**\n"
    "'정부가 오늘 발표했다'는 발표 행위의 시점일 뿐 사건(양산·시행·검토)이\n"
    "언제 일어나는지는 알려주지 않는다. 자료가 사건 자체의 시점을 명시하지\n"
    "않으면(예: '조만간', '추후', 시점 언급 없음) date_expression은 반드시\n"
    "빈 문자열이다. **'오늘'을 기본값으로 채우지 마라** — 자료 문장에 사건의\n"
    "시점으로서 '오늘'이 실제로 쓰였을 때만 쓴다.\n"
    "\n"
    "JSON 객체 하나로만 답한다.\n"
    '{"facts":[{"verdict":"new","updates_fact_id":null,'
    '"subject":"...","attribute":"...","fact_value":"...",'
    '"today_statement":"오늘의 사실을 한 문장으로",'
    '"date_expression":"사건 자체의 시점 표현만(보도 시점 아님), 없으면 빈 문자열",'
    '"source_reference":"근거 참조 ID (예: P1, G2, L3)"}]}\n'
)


@dataclass(frozen=True, slots=True)
class DiffFact:
    """Diff worker가 뽑아낸 팩트 한 건 (내부 구조화 데이터).

    `today_statement`에는 인용 마커를 요구하지 않는다 — Critic이 읽는 것은 이
    값이 아니라, Compose/Impact가 이를 바탕으로 다시 쓰는 최종 markdown이다.
    출처는 `source_reference`·`source_url`로 따로 들고 다닌다.
    """

    verdict: str
    subject: str
    attribute: str
    fact_value: str
    today_statement: str
    updates_fact_id: str | None = None
    date_expression: str = ""
    source_reference: str = ""
    source_url: str = ""


@dataclass(frozen=True, slots=True)
class DiffOutcome:
    """팩트 추출·대조 결과와 실행 기록."""

    facts: tuple[DiffFact, ...] = ()
    calls: tuple[ToolCallRecord, ...] = ()
    stop_reason: str = "final"
    base_consulted: bool = False
    input_tokens: int = 0
    output_tokens: int = 0


def describe_base_facts(facts: Sequence[ChangeHistoryFact]) -> str:
    """과거 팩트 조회 결과를 LLM이 판단할 수 있는 관찰 문자열로 만든다.

    **ID를 반드시 함께 준다.** updates_fact_id는 이 목록에서 골라 적는 값이라,
    ID가 없으면 갱신 판정을 할 수 없다.
    """
    if not facts:
        return "과거 기록 없음."
    lines = [f"과거 팩트 {len(facts)}건을 찾았다."]
    for fact in facts:
        lines.append(
            f"- id={fact.fact_id} | {fact.subject} / {fact.attribute} = "
            f"{fact.fact_value or '(값 없음)'} | {fact.statement}"
        )
    return "\n".join(lines)


def build_diff_tools(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    topic: str,
    usage: dict[str, int],
) -> list[ToolSpec]:
    """Diff worker가 사용할 읽기 전용 도구 목록을 만든다.

    topic은 LLM 인자로 노출하지 않고 클로저에 고정한다 — 도구가 다른 주제의
    팩트를 끌어오면 (user_id, topic) 격리가 깨지기 때문이다.

    Args:
        connection: 델타 테이블 조회에 사용할 DB 연결
        user_id: 조회 Scope 사용자 식별자
        topic: 보고서 주제
        usage: 도구 호출 횟수를 세는 사전(과거 대조를 실제로 했는지 기록)

    Returns:
        LLM에 노출할 ToolSpec 목록
    """

    async def search_base_facts(query: str) -> str:
        """이 토픽의 누적 과거 팩트 중 query와 관련된 것만 델타 테이블에서 조회한다."""
        if not query.strip():
            return "검색어가 비어 있다."
        usage["calls"] = usage.get("calls", 0) + 1
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=user_id)
            found = await search_change_history_facts(
                connection, user_id=user_id, topic=topic, query=query
            )
        return describe_base_facts(found)

    return [
        ToolSpec(
            name="search_base_facts",
            description=(
                "이 주제로 과거에 저장해 둔 팩트를 찾는다. 지금 뽑은 사실이 "
                "이미 알던 것인지, 값이 달라진 것인지 확인할 때 쓴다."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "찾을 대상. 주체 이름이나 속성 키워드",
                    }
                },
                "required": ["query"],
            },
            run=search_base_facts,
        ),
    ]


def _context_prompt(contexts: Sequence[ReportContextDocument]) -> str:
    """오늘 수집한 원본 문서를 참조 ID와 함께 프롬프트 블록으로 만든다."""
    blocks: list[str] = []
    size = 0
    for context in contexts:
        body = " ".join(context.content.split())[:_CONTEXT_SNIPPET_CHARS]
        block = f"[{context.reference}] {context.title}\n{body}"
        if blocks and size + len(block) > _MAX_CONTEXT_CHARS:
            break
        blocks.append(block)
        size += len(block)
    return "\n\n---\n\n".join(blocks)


def parse_diff_facts(
    text: str, *, contexts: Sequence[ReportContextDocument]
) -> list[DiffFact]:
    """Diff worker의 JSON 응답을 팩트 목록으로 변환한다.

    **응답 하나가 깨졌다고 전체를 버리지 않는다.** 쓸 수 없는 항목만 건너뛴다 —
    팩트 10건 중 1건이 형식을 어겼다고 나머지 9건까지 잃으면 그날의 델타가
    통째로 사라지기 때문이다.

    source_url은 LLM에게 묻지 않고 참조 ID로 근거 문서에서 찾아 채운다.

    Args:
        text: LLM 최종 응답
        contexts: 오늘 수집한 근거 문서 (참조 ID → URL 조회용)

    Returns:
        해석에 성공한 팩트 목록. 응답 자체가 JSON이 아니면 빈 목록.
    """
    try:
        payload = json.loads(strip_json_fence(text))
    except (ValueError, TypeError):
        logger.warning("Diff worker 응답을 해석하지 못했습니다: %s", text[:200])
        return []
    if not isinstance(payload, dict):
        return []
    raw_facts = payload.get("facts")
    if not isinstance(raw_facts, list):
        return []
    url_by_reference = {
        str(context.reference): (context.url or "") for context in contexts
    }
    allowed_references = set(url_by_reference)
    facts: list[DiffFact] = []
    for item in raw_facts:
        if not isinstance(item, dict):
            continue
        verdict = str(item.get("verdict") or "").strip().lower()
        subject = str(item.get("subject") or "").strip()
        attribute = str(item.get("attribute") or "").strip()
        statement = str(item.get("today_statement") or "").strip()
        if verdict not in _VERDICTS or not subject or not attribute or not statement:
            continue
        reference = str(item.get("source_reference") or "").strip()
        # 없는 참조를 적었으면 출처를 비운다. 조립 단계에서 인용 마커로 쓰이므로,
        # 근거 목록에 없는 참조가 새어 나가면 저장 시 Citation 조회가 깨진다.
        if reference not in allowed_references:
            reference = ""
        updates = str(item.get("updates_fact_id") or "").strip()
        facts.append(
            DiffFact(
                verdict=verdict,
                subject=subject,
                attribute=attribute,
                fact_value=str(item.get("fact_value") or "").strip(),
                today_statement=statement,
                updates_fact_id=updates or None,
                date_expression=str(item.get("date_expression") or "").strip(),
                source_reference=reference,
                source_url=url_by_reference.get(reference, ""),
            )
        )
    return facts


async def extract_delta_facts(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    topic: str,
    contexts: Sequence[ReportContextDocument],
    base_available: bool,
    model: str = "gpt-4.1-mini",
    max_iterations: int = DIFF_MAX_ITERATIONS,
    correction: str = "",
) -> DiffOutcome:
    """오늘 자료에서 팩트를 뽑고 과거 기록과 대조해 신규·갱신·중복을 가른다.

    첫 실행(base_available=False)에는 **과거 대조 부분만 생략**한다. 도구를 주지
    않고 모두 new로 표시하게 하되, 출력 형식은 그대로 유지한다 — 그래야 Compose
    입력과 델타 테이블 저장에 같은 구조를 쓸 수 있다.

    Args:
        connection: 델타 테이블 조회에 사용할 DB 연결
        user_id: 대상 사용자 식별자
        topic: 보고서 주제
        contexts: 오늘 수집한 근거 문서 (report_builder가 만든 것을 그대로 쓴다)
        base_available: 대조할 과거 팩트가 있는지
        model: 판단에 사용할 모델
        max_iterations: 도구 호출 왕복 상한
        correction: 재작업 시 앞에 붙일 교정 지시

    Returns:
        추출한 팩트와 도구 호출 기록
    """
    if not contexts:
        return DiffOutcome()
    usage: dict[str, int] = {}
    tools = (
        build_diff_tools(connection, user_id=user_id, topic=topic, usage=usage)
        if base_available
        else []
    )
    system_prompt = SYSTEM_PROMPT if base_available else FIRST_RUN_SYSTEM_PROMPT
    correction_block = f"[재작업 지시] {correction}\n\n" if correction else ""
    user_prompt = (
        f"주제: {topic}\n\n"
        + correction_block
        + "오늘 수집한 자료다. 여기에서 팩트를 뽑아라.\n\n"
        + _context_prompt(contexts)
    )
    try:
        result = await run_tool_loop(
            system_prompt,
            user_prompt,
            tools,
            model=model,
            max_iterations=max_iterations,
        )
    except Exception:
        logger.exception("Diff worker 실행에 실패해 팩트 없이 진행합니다.")
        return DiffOutcome()

    facts = parse_diff_facts(result.text, contexts=contexts)
    logger.info(
        "팩트 추출 완료: topic=%s 과거대조=%s 도구호출=%d 팩트=%d(신규 %d·갱신 %d·중복 %d)",
        topic,
        "수행" if base_available else "생략",
        len(result.calls),
        len(facts),
        sum(1 for fact in facts if fact.verdict == NEW),
        sum(1 for fact in facts if fact.verdict == UPDATED),
        sum(1 for fact in facts if fact.verdict == DUPLICATE),
    )
    return DiffOutcome(
        facts=tuple(facts),
        calls=result.calls,
        stop_reason=result.stop_reason,
        base_consulted=bool(usage.get("calls")),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def chg_002(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    topic: str,
    contexts: Sequence[ReportContextDocument],
    base_available: bool,
    model: str = "gpt-4.1-mini",
    correction: str = "",
) -> DiffOutcome:
    """[CHG-002] 팩트 추출·과거 대조.

    오늘 수집한 자료에서 팩트를 뽑고, 도구로 과거 기록과 대조해 신규·갱신·중복을
    가른다. 첫 실행이면 과거 대조 부분만 생략하고 출력 형식은 그대로 유지한다.
    """
    return await extract_delta_facts(
        connection,
        user_id=user_id,
        topic=topic,
        contexts=contexts,
        base_available=base_available,
        model=model,
        correction=correction,
    )
