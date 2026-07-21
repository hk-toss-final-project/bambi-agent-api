"""토픽 리서치 에이전트 (LangGraph 단일 그래프).

결정론적 선별 파이프라인(pipeline.run_daily)을 도구처럼 감싸고, 그 위에 얇은
에이전트 레이어를 얹는다. 에이전트가 개입하는 유일한 판단 지점은 "수집 결과가
빈약할 때 검색어를 바꿔 다시 시도할지"다. 스코어링·클러스터링·중복 판정 같은
수치 판단은 LLM에 맡기지 않고 파이프라인(결정론)에 그대로 둔다.

그래프 구조(단일 에이전트, 멀티에이전트 아님):

    START
      → plan       : 토픽을 첫 검색어로 삼는다(결정론적 초기화)
      → select     : run_daily로 수집·선별 (내부에서 클러스터 통합요약 LLM 호출)
      → (조건부 라우팅)
           · 당일 신규 아이템 있음        → write_report
           · 빈약 + 재시도 여지 있음      → reformulate → select (루프)
           · 빈약 + 재시도 소진           → write_report (주간/개념 정리 폴백)
      → reformulate: LLM이 동의어·상위개념·영문표기로 새 검색어를 제안(에이전트 판단)
      → write_report: generate_daily_report로 최종 보고서 작성
      → END

각 노드는 "무엇을, 왜" 했는지를 사람이 읽는 문장으로 trace에 남긴다(검색어가
무엇으로 바뀌었는지, 재시도할지 말지 판단 근거가 무엇인지 포함). 이 trace는
service.assist_daily_agent → web.py 결과 페이지에 그대로 노출된다.

LLM 경계(complete)와 파이프라인 경계(run_daily)를 모듈 최상위에서 import해,
테스트에서 이 두 심볼만 대체하면 실제 호출 없이 그래프 흐름을 검증할 수 있다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agent.assistant import config
from agent.assistant.pipeline import run_daily
from agent.assistant.report import generate_daily_report
from agent.assistant.summarize import complete

logger = logging.getLogger("agent.assistant.graph")

# 검색어 재구성(reformulate)을 시도할 최대 횟수. 매 시도가 수집·임베딩·요약 비용을
# 유발하므로 작게 잡는다. 0이면 재구성 없이 파이프라인을 한 번만 돌린다.
MAX_REFORMULATIONS: int = 2

_REFORMULATE_SYSTEM = (
    "너는 뉴스·영상·커뮤니티 검색어를 다듬는 한국어 리서치 보조자다. "
    "주어진 주제로 검색했지만 최근 새 소식을 충분히 찾지 못했다. "
    "같은 주제를 가리키되 더 나은 결과가 나올 만한 '검색어 하나'만 제안하라. "
    "동의어, 상위/하위 개념, 영문 표기, 관련 제품·기관명 등을 활용할 수 있다. "
    "설명 없이 검색어 문자열만, 따옴표 없이 한 줄로 답하라."
)


class AgentState(TypedDict, total=False):
    """리서치 에이전트의 그래프 상태.

    topic은 사용자의 안정적 관심사(이력·중복·유사도 기준)이고, search_query는
    이번에 수집기에 던지는 검색어(에이전트가 바꿀 수 있음)다.
    """

    topic: str
    user_id: str
    model: str
    reference_now: datetime | None
    max_reformulations: int
    search_query: str
    attempts: list[str]          # 지금까지 수집에 쓴 검색어들(중복 재시도 방지)
    selection: dict[str, object]  # 가장 최근 run_daily 결과
    # select 노드가 내린 라우팅 판단("reformulate" | "write_report"). 판단 로직을
    # select 한 곳에만 두고, 조건부 엣지는 이 값을 그대로 따르기만 한다(중복 방지).
    route_decision: str
    report_markdown: str
    trace: list[str]             # 에이전트가 내린 판단의 사람용 기록(화면에 그대로 노출)


def _has_daily_items(selection: dict[str, object]) -> bool:
    """이번 선별 결과가 '당일 신규 아이템'을 확보했는지 판단한다."""
    return selection.get("mode") == "daily" and bool(selection.get("items"))


def _plan(state: AgentState) -> AgentState:
    """토픽을 첫 검색어로 삼아 상태를 초기화한다(결정론적, LLM 미호출)."""
    topic = str(state.get("topic") or "").strip()
    return {
        "search_query": topic,
        "attempts": [],
        "trace": [f"검색어 계획: 주제 '{topic}'로 1차 검색을 시작합니다."],
        "max_reformulations": int(state.get("max_reformulations", MAX_REFORMULATIONS)),
    }


def _select(state: AgentState) -> AgentState:
    """결정론 파이프라인을 돌려 수집·선별하고, 재시도 여부까지 판단한다(도구 노드).

    "재시도할지"는 순수 판단이라 조건부 엣지(_route_after_select)에서 해도 되지만,
    그 근거(몇 번째 시도인지, 왜 계속/중단하는지)를 trace에 남기려면 여기서 계산해
    함께 반환하는 편이 낫다 — 판단 로직이 두 곳(select·router)에 흩어지지 않는다.
    """
    topic = str(state.get("topic") or "")
    query = str(state.get("search_query") or topic)

    selection = run_daily(
        topic,
        str(state.get("user_id") or ""),
        model=str(state.get("model") or "gpt-4.1-mini"),
        reference_now=state.get("reference_now"),
        search_query=query,
    )

    log = dict(selection.get("log") or {})
    exclusions = len(list(log.get("exclusions") or []))
    item_count = len(list(selection.get("items") or []))
    collect_message = (
        f"수집·선별: 검색어 '{query}' → 수집 {log.get('collected', 0)}건 중 "
        f"{exclusions}건 제외, 모드 '{selection.get('mode')}'로 판정, 선정 {item_count}건."
    )

    attempts = [*(state.get("attempts") or []), query]
    attempt_no = len(attempts)
    max_reformulations = int(state.get("max_reformulations", MAX_REFORMULATIONS))
    has_items = _has_daily_items(selection)
    can_retry = attempt_no <= max_reformulations  # 기존 재시도 한도 규칙과 동일

    if has_items:
        route = "write_report"
        judgment = (
            f"판단({attempt_no}차 시도): 당일 신규 아이템 {item_count}건을 확보했습니다. "
            "재시도 없이 보고서 작성으로 진행합니다."
        )
    elif can_retry:
        route = "reformulate"
        remaining = max_reformulations - attempt_no + 1
        judgment = (
            f"판단({attempt_no}차 시도): 당일 신규 아이템이 없습니다(모드 '{selection.get('mode')}'). "
            f"재시도 여지가 남아({remaining}회) 검색어를 재구성해 다시 시도합니다."
        )
    else:
        route = "write_report"
        judgment = (
            f"판단({attempt_no}차 시도): 당일 신규 아이템이 없고(모드 '{selection.get('mode')}') "
            f"재시도 한도({max_reformulations}회)를 모두 사용했습니다. "
            "지금까지의 결과로 보고서를 작성합니다."
        )

    # 리스트 상태는 기존 값을 읽어 확장한 '전체'를 반환한다(reducer 없이 누적 보존).
    return {
        "selection": selection,
        "attempts": attempts,
        "route_decision": route,
        "trace": [*(state.get("trace") or []), collect_message, judgment],
    }


def _reformulate(state: AgentState) -> AgentState:
    """LLM으로 새 검색어를 제안한다(에이전트의 핵심 판단 지점).

    LLM이 낸 원안(raw suggestion)을 그대로 trace에 남기고, 그걸 채택했는지
    아니면 (빈 값·중복·호출 실패 등의 이유로) 원래 토픽으로 되돌렸는지도 함께
    기록한다 — "무슨 검색어로 왜 바뀌었는지"를 화면에서 그대로 볼 수 있게 한다.
    """
    topic = str(state.get("topic") or "")
    attempts = list(state.get("attempts") or [])
    tried = ", ".join(attempts) or topic
    trace = list(state.get("trace") or [])

    try:
        raw_suggestion = complete(
            _REFORMULATE_SYSTEM,
            f"주제: {topic}\n이미 시도한 검색어: {tried}\n"
            "위와 다른, 더 나은 검색어 하나를 제안하라.",
            model=str(state.get("model") or "gpt-4.1-mini"),
        )
    except Exception as error:
        logger.info("검색어 재구성 실패, 토픽으로 되돌림: %s", error)
        message = (
            f"검색어 재구성: LLM 호출이 실패해({type(error).__name__}) "
            f"원래 주제 '{topic}'로 되돌립니다."
        )
        return {"search_query": topic, "trace": [*trace, message]}

    cleaned = " ".join(raw_suggestion.split()).strip('"').strip()

    if not cleaned:
        new_query = topic
        message = f"검색어 재구성: LLM 제안이 비어 있어 원래 주제 '{topic}'로 되돌립니다."
    elif cleaned in attempts:
        new_query = topic
        message = (
            f"검색어 재구성: LLM 제안 '{cleaned}'은 이미 시도한 검색어라 "
            f"원래 주제 '{topic}'로 되돌립니다."
        )
    else:
        new_query = cleaned
        message = f"검색어 재구성: '{topic}' → LLM 제안 '{new_query}'로 바꿔 다시 검색합니다."

    return {"search_query": new_query, "trace": [*trace, message]}


def _write_report(state: AgentState) -> AgentState:
    """선별 결과로 최종 보고서를 작성한다(LLM 노드)."""
    selection = dict(state.get("selection") or {})
    model = str(state.get("model") or "gpt-4.1-mini")
    try:
        report_markdown = generate_daily_report(selection, model=model)
    except Exception as error:
        report_markdown = ""
        errors = selection.setdefault("errors", [])
        if isinstance(errors, list):
            errors.append(f"보고서 생성 실패: {type(error).__name__}: {error}")
    message = f"보고서 작성: '{selection.get('mode')}' 모드로 브리핑을 생성했습니다."
    return {
        "report_markdown": report_markdown,
        "trace": [*(state.get("trace") or []), message],
    }


def _route_after_select(state: AgentState) -> str:
    """select 노드가 이미 내린 라우팅 판단(route_decision)을 그대로 따른다.

    판단 로직 자체는 _select에 있다 — 그래야 판단 근거를 trace에 함께 남길 수
    있다(조건부 엣지 함수는 상태를 갱신할 수 없어 trace를 못 쓴다).
    """
    return str(state.get("route_decision") or "write_report")


def build_graph():
    """리서치 에이전트 그래프를 조립해 컴파일한다."""
    builder = StateGraph(AgentState)
    builder.add_node("plan", _plan)
    builder.add_node("select", _select)
    builder.add_node("reformulate", _reformulate)
    builder.add_node("write_report", _write_report)

    builder.add_edge(START, "plan")
    builder.add_edge("plan", "select")
    builder.add_conditional_edges(
        "select",
        _route_after_select,
        {"reformulate": "reformulate", "write_report": "write_report"},
    )
    builder.add_edge("reformulate", "select")
    builder.add_edge("write_report", END)
    return builder.compile()


# 그래프 구조는 불변이라 한 번만 컴파일해 재사용한다.
_GRAPH = None


def _get_graph():
    """컴파일된 그래프를 생성해 재사용한다(그래프 구조는 불변)."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


def run_agent(
    topic: str,
    user_id: str,
    *,
    model: str = "gpt-4.1-mini",
    reference_now: datetime | None = None,
    max_reformulations: int | None = None,
) -> dict[str, object]:
    """리서치 에이전트 그래프를 실행하고 최종 선별 결과·보고서를 반환한다.

    Args:
        topic: 사용자 관심 토픽(이력·중복·유사도 기준으로 고정된 축)
        user_id: 사용자 식별자
        model: 재구성·요약·보고서에 쓸 OpenAI 모델
        reference_now: "지금" 기준 시각(테스트용). 생략하면 실제 현재 시각.
        max_reformulations: 검색어 재구성 최대 횟수. 생략하면 MAX_REFORMULATIONS.

    Returns:
        run_daily 결과(keyword, user_id, mode, cold_start, items, log, errors)에
        report_markdown, agent_trace, attempts를 더한 딕셔너리.
    """
    normalized_topic = topic.strip()
    if not normalized_topic:
        raise ValueError("키워드가 비어 있습니다.")
    normalized_user = user_id.strip()
    if not normalized_user:
        raise ValueError("사용자 식별자가 비어 있습니다.")

    initial: AgentState = {
        "topic": normalized_topic,
        "user_id": normalized_user,
        "model": model,
        "reference_now": reference_now,
        "max_reformulations": (
            MAX_REFORMULATIONS if max_reformulations is None else max_reformulations
        ),
    }
    final = _get_graph().invoke(initial)

    selection = dict(final.get("selection") or {})
    return {
        **selection,
        "report_markdown": str(final.get("report_markdown") or ""),
        "agent_trace": list(final.get("trace") or []),
        "attempts": list(final.get("attempts") or []),
    }
