"""토픽 리서치 에이전트 (LangGraph 단일 그래프).

결정론적 선별 파이프라인(pipeline.run_daily)을 도구처럼 감싸고, 그 위에 얇은
에이전트 레이어를 얹는다. 스코어링·클러스터링·중복 판정 같은 수치 판단은 LLM에
맡기지 않고 파이프라인(결정론)에 그대로 둔다.

에이전트가 개입하는 지점은 "결과가 빈약할 때 검색어를 바꿔 다시 시도할지"인데,
**빈약한 원인이 검색어로 고쳐질 수 있을 때만** 재시도한다(outcomes 모듈이 원인을
분류한다). 외부 소스 장애나 "이미 다 보고한 소식"처럼 검색어와 무관한 원인에서
재시도하면 수집·임베딩·요약 비용만 최대 3배로 늘고 결과는 그대로이기 때문이다.

그래프 구조(단일 에이전트, 멀티에이전트 아님):

    START
      → plan       : 토픽을 첫 검색어로 삼는다(결정론적 초기화)
      → select     : run_daily로 수집·선별하고 결과 원인을 분류한다
      → (조건부) 원인이 재구성 가능(no_results/low_relevance)하고 한도가 남았나?
           · 예                          → reformulate
           · 아니오(성공/장애/중복/한도)  → write_report
      → reformulate: LLM이 새 검색어를 제안한다
      → (조건부) 쓸 만한 새 검색어를 얻었나?
           · 예   → select (루프)
           · 아니오(빈 값·중복 제안·LLM 실패) → write_report (재구성 실패로 종료)
      → write_report: generate_daily_report로 최종 보고서 작성
      → END

같은 검색어로는 두 번 수집하지 않는다. LLM이 이미 시도한 검색어나 빈 값을 주면
토픽으로 되돌려 재실행하는 대신 재구성 실패로 보고 그 시점 결과로 보고서를 쓴다.

trace는 사람이 읽는 문장이 아니라 구조화된 이벤트(node/status/reason/query/
errors/duration_ms/message)로 쌓아, 감사·설명 가능성에 쓸 수 있게 한다. 시도별
오류도 마지막 시도 것만 남기지 않고 전부 누적한다.

LLM 경계(complete)와 파이프라인 경계(run_daily)를 모듈 최상위에서 import해,
테스트에서 이 두 심볼만 대체하면 실제 호출 없이 그래프 흐름을 검증할 수 있다.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agent.assistant.features import outcomes
from agent.assistant.features.pipeline import run_daily
from agent.assistant.features.report import generate_daily_report
from agent.assistant.features.summarize import complete

logger = logging.getLogger("agent.assistant.features.graph")

# 검색어 재구성(reformulate)을 시도할 최대 횟수. 매 시도가 수집·임베딩·요약 비용을
# 유발하므로 작게 잡는다. 0이면 재구성 없이 파이프라인을 한 번만 돌린다.
MAX_REFORMULATIONS: int = 2

# trace 이벤트의 status 값.
STATUS_OK = "ok"          # 정상 진행
STATUS_RETRY = "retry"    # 재시도하기로 판단
STATUS_STOP = "stop"      # 재시도하지 않고 종료하기로 판단
STATUS_FAILED = "failed"  # 이 단계가 실패

# 재구성 검색어로 허용할 최대 길이(공백 포함). 이보다 길면 검색어가 아니라 키워드
# 나열·설명문일 가능성이 높다. 벤치마크(bench/assistant_reformulation)에서 한 글자
# 주제("K")에 LLM이 "케이팝 K-pop K드라마 …" 52자를 반환한 사례로 확인됐다.
MAX_QUERY_CHARS: int = 40

REFORMULATE_SYSTEM = (
    "너는 뉴스·영상·커뮤니티 검색어를 다듬는 한국어 리서치 보조자다. "
    "주어진 주제로 검색했지만 최근 새 소식을 충분히 찾지 못했다. "
    "같은 주제를 가리키되 더 나은 결과가 나올 만한 '검색어 하나'만 제안하라. "
    "동의어, 상위/하위 개념, 영문 표기, 관련 제품·기관명 등을 활용할 수 있다. "
    "여러 후보를 나열하지 말고 단어 2~5개, 공백 포함 30자 이내로 짧게 만들어라. "
    "설명 없이 검색어 문자열만, 따옴표 없이 한 줄로 답하라."
)


def build_reformulate_prompt(topic: str, attempts: list[str]) -> str:
    """검색어 재구성 user 프롬프트를 만든다.

    벤치마크(bench/assistant_reformulation)가 그래프와 똑같은 프롬프트를 평가할 수
    있도록 조립을 함수로 분리한다 — 프롬프트가 두 곳에 복제되면 벤치 결과가 실제
    동작과 어긋난다.
    """
    tried = ", ".join(attempts) or topic
    return (
        f"주제: {topic}\n이미 시도한 검색어: {tried}\n"
        "위와 다른, 더 나은 검색어 하나를 제안하라."
    )


def normalize_suggestion(raw_suggestion: str) -> str:
    """LLM 제안에서 공백·따옴표를 정리해 검색어 한 줄로 만든다."""
    return " ".join(raw_suggestion.split()).strip('"').strip()


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
    attempts: list[str]              # 지금까지 수집에 쓴 검색어들(중복 재시도 방지)
    attempt_records: list[dict[str, object]]  # 시도별 {query, outcome, mode, items, errors}
    selection: dict[str, object]     # 가장 최근 run_daily 결과
    accumulated_errors: list[str]    # 모든 시도의 오류(마지막 시도 것만 남기지 않는다)
    # select/reformulate 노드가 내린 라우팅 판단. 조건부 엣지는 이 값을 따르기만 한다
    # (판단 로직을 노드에 두어야 그 근거를 trace에 함께 남길 수 있다).
    route_decision: str
    report_markdown: str
    trace: list[dict[str, object]]   # 구조화된 판단 이벤트


def _event(
    node: str,
    status: str,
    *,
    reason: str = "",
    query: str = "",
    errors: list[str] | None = None,
    duration_ms: int = 0,
    message: str = "",
) -> dict[str, object]:
    """구조화된 trace 이벤트 하나를 만든다."""
    return {
        "node": node,
        "status": status,
        "reason": reason,
        "query": query,
        "errors": list(errors or []),
        "duration_ms": duration_ms,
        "message": message,
    }


def _plan(state: AgentState) -> AgentState:
    """토픽을 첫 검색어로 삼아 상태를 초기화한다(결정론적, LLM 미호출)."""
    topic = str(state.get("topic") or "").strip()
    return {
        "search_query": topic,
        "attempts": [],
        "attempt_records": [],
        "accumulated_errors": [],
        "trace": [
            _event(
                "plan",
                STATUS_OK,
                reason="initial_query",
                query=topic,
                message=f"검색어 계획: 주제 '{topic}'로 1차 검색을 시작합니다.",
            )
        ],
        "max_reformulations": int(state.get("max_reformulations", MAX_REFORMULATIONS)),
    }


def _select(state: AgentState) -> AgentState:
    """파이프라인을 돌려 수집·선별하고, 원인을 분류해 재시도 여부까지 판단한다.

    재시도 판단을 조건부 엣지가 아니라 이 노드에서 하는 이유는, 판단 근거(원인
    코드·시도 횟수·남은 한도)를 trace 이벤트로 함께 남기기 위해서다. 조건부 엣지
    함수는 상태를 갱신할 수 없어 근거를 기록할 수 없다.
    """
    topic = str(state.get("topic") or "")
    query = str(state.get("search_query") or topic)

    started = time.monotonic()
    selection = run_daily(
        topic,
        str(state.get("user_id") or ""),
        model=str(state.get("model") or "gpt-4.1-mini"),
        reference_now=state.get("reference_now"),
        search_query=query,
    )
    duration_ms = int((time.monotonic() - started) * 1000)

    log = dict(selection.get("log") or {})
    attempt_errors = [str(error) for error in (selection.get("errors") or [])]
    item_count = len(list(selection.get("items") or []))
    outcome = outcomes.classify(selection)

    attempts = [*(state.get("attempts") or []), query]
    attempt_no = len(attempts)
    max_reformulations = int(state.get("max_reformulations", MAX_REFORMULATIONS))
    # attempts에는 이번 시도가 이미 포함돼 있으므로, 남은 재구성 여지는 (한도 - 재구성 횟수).
    can_retry = attempt_no <= max_reformulations

    collect_event = _event(
        "select",
        STATUS_FAILED if attempt_errors else STATUS_OK,
        reason=outcome,
        query=query,
        errors=attempt_errors,
        duration_ms=duration_ms,
        message=(
            f"수집·선별: 검색어 '{query}' → 수집 {log.get('collected', 0)}건 중 "
            f"{len(list(log.get('exclusions') or []))}건 제외, "
            f"모드 '{selection.get('mode')}'로 판정, 선정 {item_count}건."
        ),
    )

    if outcome == outcomes.SUCCESS:
        route, status = "write_report", STATUS_OK
        judgment = (
            f"판단({attempt_no}차 시도): 당일 신규 아이템 {item_count}건을 확보했습니다. "
            "재시도 없이 보고서 작성으로 진행합니다."
        )
    elif not outcomes.should_reformulate(outcome):
        # 외부 장애·중복 소식·점수 미달처럼 검색어로 해결되지 않는 원인이다.
        route, status = "write_report", STATUS_STOP
        judgment = (
            f"판단({attempt_no}차 시도): {outcomes.describe(outcome)} "
            "검색어를 바꿔도 해결되지 않는 원인이라 재시도하지 않고 보고서를 작성합니다."
        )
    elif not can_retry:
        route, status = "write_report", STATUS_STOP
        judgment = (
            f"판단({attempt_no}차 시도): {outcomes.describe(outcome)} "
            f"재시도 한도({max_reformulations}회)를 모두 사용해 지금까지의 결과로 보고서를 작성합니다."
        )
    else:
        route, status = "reformulate", STATUS_RETRY
        remaining = max_reformulations - attempt_no + 1
        judgment = (
            f"판단({attempt_no}차 시도): {outcomes.describe(outcome)} "
            f"검색어로 해결될 수 있는 원인이고 재시도 여지가 남아({remaining}회) "
            "검색어를 재구성해 다시 시도합니다."
        )

    judgment_event = _event(
        "select",
        status,
        reason=outcome,
        query=query,
        duration_ms=0,
        message=judgment,
    )

    record = {
        "query": query,
        "outcome": outcome,
        "mode": selection.get("mode"),
        "items": item_count,
        "errors": attempt_errors,
        "duration_ms": duration_ms,
    }
    # 이전 시도의 오류가 마지막 시도 결과에 덮여 사라지지 않도록 전부 누적한다.
    accumulated = [
        *(state.get("accumulated_errors") or []),
        *(f"[{attempt_no}차 시도] {error}" for error in attempt_errors),
    ]

    return {
        "selection": selection,
        "attempts": attempts,
        "attempt_records": [*(state.get("attempt_records") or []), record],
        "accumulated_errors": accumulated,
        "route_decision": route,
        "trace": [*(state.get("trace") or []), collect_event, judgment_event],
    }


def _reformulate(state: AgentState) -> AgentState:
    """LLM으로 새 검색어를 제안한다(에이전트의 핵심 판단 지점).

    쓸 만한 새 검색어를 못 얻으면(빈 값·이미 시도한 검색어·LLM 실패) 토픽으로
    되돌려 같은 검색을 반복하지 않고, 재구성 실패로 보고 보고서 작성으로 넘긴다.
    같은 검색어를 다시 돌리는 것은 결과가 동일함이 보장된 순수 비용이기 때문이다.
    """
    topic = str(state.get("topic") or "")
    attempts = list(state.get("attempts") or [])
    trace = list(state.get("trace") or [])

    started = time.monotonic()
    try:
        raw_suggestion = complete(
            REFORMULATE_SYSTEM,
            build_reformulate_prompt(topic, attempts),
            model=str(state.get("model") or "gpt-4.1-mini"),
        )
    except Exception as error:
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info("검색어 재구성 LLM 실패: %s", error)
        message = (
            f"검색어 재구성 실패: LLM 호출이 실패해({type(error).__name__}) "
            "재시도를 중단하고 지금까지의 결과로 보고서를 작성합니다."
        )
        return {
            "route_decision": "write_report",
            "accumulated_errors": [
                *(state.get("accumulated_errors") or []),
                f"검색어 재구성 실패: {type(error).__name__}: {error}",
            ],
            "trace": [
                *trace,
                _event(
                    "reformulate",
                    STATUS_FAILED,
                    reason="llm_error",
                    errors=[f"{type(error).__name__}: {error}"],
                    duration_ms=duration_ms,
                    message=message,
                ),
            ],
        }

    duration_ms = int((time.monotonic() - started) * 1000)
    cleaned = normalize_suggestion(raw_suggestion)

    if not cleaned:
        reason, message = (
            "empty_suggestion",
            "검색어 재구성 실패: LLM이 빈 제안을 돌려줘 재시도를 중단하고 "
            "지금까지의 결과로 보고서를 작성합니다.",
        )
    elif len(cleaned) > MAX_QUERY_CHARS:
        # 검색어가 아니라 키워드 나열·설명문을 받은 경우다. 그대로 검색하면
        # 무관한 결과만 나오므로 재시도하지 않는다.
        reason, message = (
            "too_long_suggestion",
            f"검색어 재구성 실패: LLM 제안이 {len(cleaned)}자로 너무 길어(허용 "
            f"{MAX_QUERY_CHARS}자) 검색어로 쓸 수 없습니다. 지금까지의 결과로 보고서를 작성합니다.",
        )
    elif cleaned in attempts:
        reason, message = (
            "duplicate_suggestion",
            f"검색어 재구성 실패: LLM 제안 '{cleaned}'은 이미 시도한 검색어라 "
            "같은 검색을 반복하지 않고 지금까지의 결과로 보고서를 작성합니다.",
        )
    else:
        return {
            "route_decision": "select",
            "search_query": cleaned,
            "trace": [
                *trace,
                _event(
                    "reformulate",
                    STATUS_OK,
                    reason="new_query",
                    query=cleaned,
                    duration_ms=duration_ms,
                    message=(
                        f"검색어 재구성: '{topic}' → LLM 제안 '{cleaned}'로 바꿔 다시 검색합니다."
                    ),
                ),
            ],
        }

    return {
        "route_decision": "write_report",
        "trace": [
            *trace,
            _event(
                "reformulate",
                STATUS_FAILED,
                reason=reason,
                query=cleaned,
                duration_ms=duration_ms,
                message=message,
            ),
        ],
    }


def _write_report(state: AgentState) -> AgentState:
    """선별 결과로 최종 보고서를 작성한다(LLM 노드)."""
    selection = dict(state.get("selection") or {})
    model = str(state.get("model") or "gpt-4.1-mini")
    trace = list(state.get("trace") or [])

    started = time.monotonic()
    try:
        report_markdown = generate_daily_report(selection, model=model)
    except Exception as error:
        duration_ms = int((time.monotonic() - started) * 1000)
        detail = f"보고서 생성 실패: {type(error).__name__}: {error}"
        logger.info("%s", detail)
        return {
            "report_markdown": "",
            "accumulated_errors": [*(state.get("accumulated_errors") or []), detail],
            "trace": [
                *trace,
                _event(
                    "write_report",
                    STATUS_FAILED,
                    reason="report_error",
                    errors=[f"{type(error).__name__}: {error}"],
                    duration_ms=duration_ms,
                    message=f"보고서 작성 실패: {type(error).__name__} 오류로 본문을 만들지 못했습니다.",
                ),
            ],
        }

    duration_ms = int((time.monotonic() - started) * 1000)
    # 예외는 없었지만 본문이 비어 나온 경우도 성공으로 기록하지 않는다.
    empty = not report_markdown.strip()
    return {
        "report_markdown": report_markdown,
        "trace": [
            *trace,
            _event(
                "write_report",
                STATUS_FAILED if empty else STATUS_OK,
                reason="empty_report" if empty else str(selection.get("mode") or ""),
                duration_ms=duration_ms,
                message=(
                    "보고서 작성: 본문이 비어 있어 표시할 내용이 없습니다."
                    if empty
                    else f"보고서 작성: '{selection.get('mode')}' 모드로 브리핑을 생성했습니다."
                ),
            ),
        ],
    }


def _route(state: AgentState) -> str:
    """노드가 이미 내린 라우팅 판단(route_decision)을 그대로 따른다."""
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
        "select", _route, {"reformulate": "reformulate", "write_report": "write_report"}
    )
    # 재구성이 쓸 만한 새 검색어를 못 만들면 select로 돌아가지 않고 바로 보고서로 간다.
    builder.add_conditional_edges(
        "reformulate", _route, {"select": "select", "write_report": "write_report"}
    )
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
        run_daily 결과(keyword, user_id, mode, cold_start, items, log)에 더해
        errors(모든 시도 누적), report_markdown, agent_trace(구조화 이벤트),
        attempts(시도한 검색어), attempt_records(시도별 요약), outcome(최종 원인).
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
    records = list(final.get("attempt_records") or [])
    return {
        **selection,
        # 마지막 시도의 오류만 남기지 않고, 모든 시도에서 누적한 오류를 돌려준다.
        "errors": list(final.get("accumulated_errors") or []),
        "report_markdown": str(final.get("report_markdown") or ""),
        "agent_trace": list(final.get("trace") or []),
        "attempts": list(final.get("attempts") or []),
        "attempt_records": records,
        "outcome": str(records[-1]["outcome"]) if records else outcomes.UNKNOWN,
    }
