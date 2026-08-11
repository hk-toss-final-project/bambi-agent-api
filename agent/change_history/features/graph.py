"""변경점(Delta) 추적 서브그래프 — Supervisor + 워커 + 도구.

토글이 켜지면 기존 report_builder의 `generate` 노드를 **대체**한다(그 앞에
generate가 도는 게 아니다). 즉 여기서 쓰는 글은 아직 아무도 검증하지 않은
완전히 새 콘텐츠이며, 뒤에 오는 기존 review(Critic)에서 처음으로 검증받는다.

    prepare → supervisor ⇄ {diff, compose, impact, validate} → assemble → store

Supervisor는 순서대로 호출하는 라우터가 아니라 **상태를 보고 실제로 다른 경로를
택하는 판단 노드**다.

이 보고서는 "달라진 것만" 보여주는 게 아니라 **평소와 같은 정보요약보고서 +
달라진 점 하이라이트**다. 그래서 Diff가 뽑은 팩트(신규·갱신·유지) 전부가
Compose까지 흘러가 "핵심 요약·맥락"의 재료가 되고, "이번에 달라진 점" 섹션에만
신규·갱신 팩트가 따로 추려 들어간다.

  ① Base 팩트가 없으면(첫 실행) Diff worker의 **과거 대조만** 생략한다.
     worker 자체를 건너뛰지 않는 이유는 구조화 출력 형식이 유지돼야 Compose
     입력과 델타 테이블 저장에 그대로 쓸 수 있기 때문이다.
  ② 오늘 팩트를 하나도 못 뽑았으면(수집 실패 등) 요약을 쓸 재료가 없다 — 이건
     "달라진 게 없다"와 다른 **실패**다. 예외를 올려 호출자가 기존 generate()
     경로로 되돌아가게 한다. 반대로 팩트는 있는데 전부 유지(중복)뿐이면 실패가
     아니다 — Compose는 정상적으로 돌려 요약을 쓰되, 신규·갱신이 없으니 Impact와
     "이번에 달라진 점" 섹션만 건너뛴다.
  ③ 검증 실패 시 전체 재시도가 아니라 문제가 난 워커만 1회 재작업시킨다.
     재작업 후에도 실패하면 무한 루프를 돌지 말고 해당 항목을 드롭 + 플래그를
     남기고 통과한다.
"""

from __future__ import annotations

import logging
from datetime import date
from contextlib import asynccontextmanager
from typing import Any

from langgraph.graph import END, StateGraph
from psycopg import AsyncConnection

from agent.report_builder.api import evaluate_report
from agent.state import ChangeHistoryState
from infrastructure.persistence.api import (
    list_change_history_facts,
    load_latest_change_history_run,
    load_latest_report_snapshot,
    persist_change_history_run,
    set_personal_wiki_scope,
)
from shared.change_history_models import DUPLICATE, NewChangeHistoryFact
from shared.report_models import GeneratedReportContent, ReportContextDocument

from .assembly import chg_006
from .compose import ComposeOutcome, chg_003
from .config import current_reference_date, impact_model
from .diff import DiffFact, chg_002
from .impact import ImpactOutcome, chg_004
from .validation import (
    COMPOSE_WORKER,
    DIFF_WORKER,
    IMPACT_WORKER,
    ValidationOutcome,
    chg_005,
)

logger = logging.getLogger("agent.change_history.graph")

type DictRow = dict[str, Any]

# 워커 하나당 재작업 상한. 재작업 후에도 실패하면 드롭 + 플래그로 통과시킨다 —
# 검증이 계속 흠을 잡으면 리포트 하나에 LLM 호출이 무한히 늘어난다.
WORKER_MAX_RETRIES = 1

_DIFF_CORRECTION = (
    "이전 시도에서 갱신 대상으로 찍은 과거 팩트 ID가 실제 기록에 없었다. "
    "updates_fact_id에는 search_base_facts가 돌려준 id 값을 그대로 적고, "
    "확인하지 못한 팩트는 new로 처리해라."
)
_COMPOSE_CORRECTION = (
    "이전 시도의 타임라인 날짜가 규칙에 맞지 않았다. 날짜는 반드시 기준일을 "
    "기준으로 환산한 YYYY-MM-DD 절대 날짜로 적고, 확정할 수 없으면 date를 "
    "비우고 precision을 unknown으로 둬라."
)
_CITATION_CORRECTION = (
    "이전 시도의 서술에 유효한 인용 마커가 없었다. 팩트를 서술할 때마다 그 "
    "팩트의 참조 ID를 [G2] 형식으로 붙여라. 문단마다 최소 하나는 있어야 한다."
)

# 검증에서 나온 사유별 교정 지시. "다시 써라"만으로는 같은 글이 나오므로,
# 무엇이 문제였는지를 워커에게 그대로 전달한다.
_CORRECTION_BY_REASON = {
    "overview_missing_citation": _CITATION_CORRECTION,
    "implications_missing_citation": _CITATION_CORRECTION,
    "timeline_date_unparsable": _COMPOSE_CORRECTION,
    "timeline_date_out_of_range": _COMPOSE_CORRECTION,
    "timeline_fact_index_missing": _COMPOSE_CORRECTION,
    "updates_fact_id_not_found": _DIFF_CORRECTION,
}


def build_change_history_graph(
    connection: AsyncConnection[DictRow],
    db_lock: Any | None = None,
) -> Any:
    """변경점 추적 서브그래프의 노드와 엣지를 조립해 컴파일된 그래프를 반환한다.

    prepare(Base 조회) → supervisor(판단) → diff/compose/impact/validate →
    assemble(조립, 코드) → store(델타 저장) 순으로 잇는다. Supervisor로 되돌아오는
    엣지가 있어, 워커 재작업과 "변화 없음" 단축 경로가 같은 판단 노드를 지난다.

    빌드 시점에는 connection을 사용하지 않고 노드 클로저만 구성하므로,
    /dev/graphs 레지스트리는 None 스텁으로 구조를 추출할 수 있다.
    """

    @asynccontextmanager
    async def _tx_scope() -> AsyncIterator[None]:
        if db_lock is not None:
            async with db_lock:
                async with connection.transaction():
                    yield
        else:
            async with connection.transaction():
                yield

    async def prepare(state: ChangeHistoryState) -> dict[str, Any]:
        """직전 보고서 맥락과 과거 팩트 유무를 한 조회 Transaction으로 읽는다.

        Base는 성격이 다른 두 갈래다. (a)맥락 요약은 직전 publish_snapshot에서,
        (b)구조화된 과거 팩트는 델타 테이블에서 온다. Overview는 (a)를 딛고
        쓰고, Diff는 (b)를 대조 대상으로 삼는다.
        """
        user_id = state["user_id"]
        topic = state["topic"]
        async with _tx_scope():
            await set_personal_wiki_scope(connection, user_id=user_id)
            snapshot = await load_latest_report_snapshot(
                connection, user_id=user_id, topic=topic
            )
            previous_run = await load_latest_change_history_run(
                connection, user_id=user_id, topic=topic
            )
            base_facts = await list_change_history_facts(
                connection, user_id=user_id, topic=topic, limit=1
            )
        base_available = bool(base_facts)
        base_summary = ""
        if snapshot is not None:
            base_summary = snapshot.summary or snapshot.body
        logger.info(
            "델타 Base 확인: topic=%s 과거팩트=%s 직전실행=%s",
            topic,
            "있음" if base_available else "없음",
            previous_run.run_id if previous_run else "없음",
        )
        return {
            "base_summary": base_summary,
            "base_available": base_available,
            "base_run_id": previous_run.run_id if previous_run else "",
            "is_first_run": not base_available,
            "dropped_flags": [],
        }

    def _all_facts(state: ChangeHistoryState) -> list[DiffFact]:
        """오늘 확인된 팩트 전체(신규·갱신·유지)를 반환한다.

        Compose는 이걸 받아 "핵심 요약·맥락"을 쓴다 — 안 바뀐 사실도 배경으로
        자연스럽게 녹여야 정보요약보고서 역할을 하기 때문이다.
        """
        return [
            fact
            for fact in (state.get("diff_facts") or [])
            if isinstance(fact, DiffFact)
        ]

    def _highlight_facts(state: ChangeHistoryState) -> list[DiffFact]:
        """이번에 달라진 팩트(신규·갱신)만 추린다.

        "이번에 달라진 점" 섹션·Impact·타임라인·저장은 이것만 쓴다. 유지(중복)
        팩트는 이미 DB에 있는 값과 같으므로 다시 저장하지 않는다.
        """
        return [fact for fact in _all_facts(state) if fact.verdict != DUPLICATE]

    async def supervisor(state: ChangeHistoryState) -> dict[str, Any]:
        """상태를 보고 다음에 어느 워커로 갈지 정한다.

        이 노드는 LLM을 부르지 않는다. 판단 근거가 "무엇이 이미 끝났는가",
        "무엇이 실패했는가", "재작업 예산이 남았는가"처럼 세는 문제라,
        코드가 정하는 편이 결정적이고 무료다.
        """
        if not state.get("diff_done"):
            return {"route": "diff"}

        all_facts = _all_facts(state)
        if not all_facts:
            # ② 오늘 자료에서 팩트를 하나도 못 뽑았다 — 요약을 쓸 재료가 없다.
            # "달라진 게 없다"와는 다른 실패다. 예외를 올려 호출자(agent/graph.py의
            # change_history 노드)가 기존 generate() 경로로 되돌아가게 한다.
            raise RuntimeError(
                f"오늘 자료에서 팩트를 하나도 추출하지 못했습니다: topic={state['topic']}"
            )

        compose_outcome = state.get("compose")
        compose_attempts = int(state.get("compose_attempts") or 0)
        if compose_attempts == 0:
            return {"route": "compose"}
        if (
            isinstance(compose_outcome, ComposeOutcome)
            and compose_outcome.failed
            and compose_attempts <= WORKER_MAX_RETRIES
        ):
            return {"route": "compose"}
        # 재작업 후에도 실패했다면 조립이 대체 문구로 채우고 넘어간다.

        # 이번에 달라진 게 없으면(전부 유지) Impact가 해석할 대상도 없다 —
        # 건너뛴다. Compose는 이미 위에서 정상적으로 돌았으므로 요약은 그대로 나간다.
        highlight_facts = _highlight_facts(state)
        if highlight_facts:
            impact_attempts = int(state.get("impact_attempts") or 0)
            impact_outcome = state.get("impact")
            if impact_attempts == 0:
                return {"route": "impact"}
            if (
                isinstance(impact_outcome, ImpactOutcome)
                and impact_outcome.failed
                and impact_attempts <= WORKER_MAX_RETRIES
            ):
                return {"route": "impact"}

        if not state.get("validated"):
            return {"route": "validate"}

        # ③ 검증에서 걸린 항목이 있으면 문제가 난 워커만 1회 재작업시킨다.
        validation = state.get("validation")
        if isinstance(validation, ValidationOutcome) and validation.problems:
            failed = validation.failed_workers
            if DIFF_WORKER in failed and int(state.get("diff_attempts") or 0) <= WORKER_MAX_RETRIES:
                # 팩트 목록이 바뀌면 그것을 입력으로 삼은 Compose·Impact 출력도
                # 낡은 것이 되므로 함께 다시 만든다. 재작업의 방아쇠는 어디까지나
                # 문제가 난 워커(diff) 하나다.
                return {
                    "route": "diff",
                    "compose": None,
                    "compose_attempts": 0,
                    "impact": None,
                    "impact_attempts": 0,
                    "validated": False,
                }
            if (
                COMPOSE_WORKER in failed
                and int(state.get("compose_attempts") or 0) <= WORKER_MAX_RETRIES
            ):
                return {"route": "compose", "validated": False}
            if (
                IMPACT_WORKER in failed
                and int(state.get("impact_attempts") or 0) <= WORKER_MAX_RETRIES
            ):
                return {"route": "impact", "validated": False}
            # 재작업 예산이 끝났다. 드롭 플래그만 남기고 통과시킨다.
            flags = list(state.get("dropped_flags") or [])
            flags.extend(problem.as_flag() for problem in validation.problems)
            logger.info(
                "검증 실패 항목 %d건을 드롭하고 진행합니다: topic=%s",
                len(validation.problems),
                state["topic"],
            )
            return {"route": "assemble", "dropped_flags": flags}
        return {"route": "assemble"}

    def route_from_supervisor(state: ChangeHistoryState) -> str:
        """Supervisor가 정한 목적지를 조건부 엣지로 넘긴다."""
        return str(state.get("route") or "assemble")

    async def diff(state: ChangeHistoryState) -> dict[str, Any]:
        """오늘 자료에서 팩트를 뽑고 과거 기록과 대조한다(도구 에이전트)."""
        attempts = int(state.get("diff_attempts") or 0)
        outcome = await chg_002(
            connection,
            user_id=state["user_id"],
            topic=state["topic"],
            contexts=[
                context
                for context in state.get("contexts") or []
                if isinstance(context, ReportContextDocument)
            ],
            base_available=bool(state.get("base_available")),
            model=state["model"],
            correction=_correction_for(state, DIFF_WORKER) if attempts else "",
        )
        duplicates = sum(1 for fact in outcome.facts if fact.verdict == DUPLICATE)
        return {
            "diff_facts": list(outcome.facts),
            "diff_done": True,
            "diff_attempts": attempts + 1,
            "duplicate_count": duplicates,
            **_accumulate_tokens(state, outcome),
        }

    async def compose(state: ChangeHistoryState) -> dict[str, Any]:
        """오늘 확인된 팩트 전체로 핵심 요약과 타임라인을 한 번의 LLM 호출로 만든다.

        신규·갱신·유지 팩트를 모두 넘긴다 — 여기서 만드는 요약이 "달라진 것만"이
        아니라 지금 전체 상황을 설명하는 정보요약보고서 역할을 하기 때문이다.
        """
        attempts = int(state.get("compose_attempts") or 0)
        correction = _correction_for(state, COMPOSE_WORKER) if attempts else ""
        outcome = await chg_003(
            topic=state["topic"],
            facts=_all_facts(state),
            reference_date=_state_reference_date(state),
            base_summary=str(state.get("base_summary") or ""),
            model=state["model"],
            correction=correction,
        )
        return {
            "compose": outcome,
            "compose_attempts": attempts + 1,
            **_accumulate_tokens(state, outcome),
        }

    async def impact(state: ChangeHistoryState) -> dict[str, Any]:
        """이번에 달라진 팩트로 파급효과와 확인 사항을 추론한다.

        유지(중복) 팩트는 뺀다 — 안 바뀐 것을 놓고 "앞으로 뭘 지켜봐야 하는지"를
        새로 추론할 이유가 없다. Supervisor가 달라진 게 없으면 이 노드 자체를
        건너뛰므로, 여기 도달했다는 것은 highlight_facts가 비어 있지 않다는 뜻이다.
        """
        attempts = int(state.get("impact_attempts") or 0)
        outcome = await chg_004(
            topic=state["topic"],
            facts=_highlight_facts(state),
            # 추론 난이도가 높은 노드라 필요하면 여기만 더 강한 모델로 올린다.
            model=impact_model(state["model"]),
            correction=_correction_for(state, IMPACT_WORKER) if attempts else "",
        )
        return {
            "impact": outcome,
            "impact_attempts": attempts + 1,
            **_accumulate_tokens(state, outcome),
        }

    async def validate(state: ChangeHistoryState) -> dict[str, Any]:
        """조립 전에 팩트 정합성·날짜 타당성·인용 마커를 코드로 검사한다.

        Compose의 overview가 유지 팩트도 인용할 수 있으므로, 인용 마커 검사의
        "사용 가능한 참조" 범위도 전체 팩트(all_facts) 기준이어야 한다 — highlight만
        기준으로 삼으면 유지 팩트의 정당한 인용을 오탐으로 걸러낸다.
        """
        compose_outcome = state.get("compose")
        impact_outcome = state.get("impact")
        timeline = (
            compose_outcome.timeline
            if isinstance(compose_outcome, ComposeOutcome)
            else ()
        )
        outcome = await chg_005(
            connection,
            user_id=state["user_id"],
            topic=state["topic"],
            facts=_all_facts(state),
            timeline=timeline,
            reference_date=_state_reference_date(state),
            overview=(
                compose_outcome.overview
                if isinstance(compose_outcome, ComposeOutcome)
                else ""
            ),
            implications=(
                impact_outcome.implications
                if isinstance(impact_outcome, ImpactOutcome)
                else ""
            ),
        )
        return {"validation": outcome, "validated": True}

    async def assemble(state: ChangeHistoryState) -> dict[str, Any]:
        """검증을 통과한 출력으로 정보요약보고서를 조립한다.

        Compose의 overview("핵심 요약·맥락")는 이미 전체 그림(신규·갱신·유지)을
        담고 있으므로 그대로 쓴다. "이번에 달라진 점" 섹션만
        validation.facts에서 신규·갱신을 추려 따로 만든다.

        조립 뒤 기존 무료 품질 검사(quality.evaluate_report)를 그대로 적용한다.
        이제는 달라진 게 없어도(highlight_items가 비어도) Compose가 실제 요약을
        전체 팩트로 써서 인용이 정상적으로 존재하므로, 검사를 건너뛸 이유가 없다
        — "변화 없음"이라고 본문 자체가 비거나 짧아지지 않는다.
        """
        validation = state.get("validation")
        validated_facts = (
            validation.facts if isinstance(validation, ValidationOutcome) else ()
        )
        highlight_items = tuple(
            item for item in validated_facts if item.fact.verdict != DUPLICATE
        )
        no_change = not highlight_items
        compose_outcome = state.get("compose")
        impact_outcome = state.get("impact")
        contexts = [
            context
            for context in state.get("contexts") or []
            if isinstance(context, ReportContextDocument)
        ]
        generated = await chg_006(
            topic=state["topic"],
            reference_date=_state_reference_date(state),
            highlight_facts=highlight_items,
            compose=(
                compose_outcome
                if isinstance(compose_outcome, ComposeOutcome)
                else ComposeOutcome()
            ),
            impact=(
                impact_outcome
                if isinstance(impact_outcome, ImpactOutcome)
                else ImpactOutcome()
            ),
            contexts=contexts,
            is_first_run=bool(state.get("is_first_run")),
        )
        quality_outcome = evaluate_report(
            generated, context_count=len(contexts)
        ).outcome
        logger.info(
            "델타 보고서 조립 완료: topic=%s 달라진 점 %d건 품질=%s",
            state["topic"],
            len(highlight_items),
            quality_outcome,
        )
        return {
            "generated": generated,
            "quality_outcome": quality_outcome,
            "no_change": no_change,
        }

    async def store(state: ChangeHistoryState) -> dict[str, Any]:
        """이번에 달라진 팩트와 실행 메타를 델타 테이블에 저장한다.

        **유지(중복) 팩트는 저장하지 않는다** — 이미 DB에 있는 값과 같으므로
        다시 넣으면 같은 사실이 실행마다 새 Row로 쌓인다. **첫 실행도 예외 없이
        저장한다.** 이 저장은 출력이 아니라 다음 실행의 Base 재료다. 저장 실패가
        이미 만들어진 보고서를 못 나가게 하면 안 되므로 예외는 경고 로그로만 남긴다
        (다음 실행이 복구 경로다).
        """
        validation = state.get("validation")
        validated_facts = (
            validation.facts if isinstance(validation, ValidationOutcome) else ()
        )
        highlight_items = [
            item for item in validated_facts if item.fact.verdict != DUPLICATE
        ]
        payload = [
            NewChangeHistoryFact(
                subject=item.fact.subject,
                attribute=item.fact.attribute,
                fact_value=item.fact.fact_value,
                statement=item.fact.today_statement,
                verdict=item.fact.verdict,
                supersedes_fact_id=item.fact.updates_fact_id,
                before_value=item.before_value,
                occurred_on=item.occurred_on,
                date_precision=item.date_precision,
                source_reference=item.fact.source_reference or None,
                source_url=item.fact.source_url or None,
            )
            for item in highlight_items
        ]
        try:
            async with _tx_scope():
                await set_personal_wiki_scope(connection, user_id=state["user_id"])
                persisted = await persist_change_history_run(
                    connection,
                    user_id=state["user_id"],
                    topic=state["topic"],
                    reference_date=_state_reference_date(state),
                    facts=payload,
                    job_id=state.get("job_id"),
                    base_run_id=str(state.get("base_run_id") or "") or None,
                    is_first_run=bool(state.get("is_first_run")),
                    outcome="no_change" if state.get("no_change") else "delta",
                    duplicate_fact_count=int(state.get("duplicate_count") or 0),
                    dropped_flags=list(state.get("dropped_flags") or []),
                )
        except Exception:  # noqa: BLE001 — 저장 실패가 발행을 막으면 안 된다
            logger.warning(
                "델타 팩트 저장에 실패했습니다 — 보고서는 그대로 발행합니다 (topic=%s)",
                state["topic"],
                exc_info=True,
            )
            return {"run_id": "", "stored_fact_count": 0}
        return {
            "run_id": persisted.run_id,
            "stored_fact_count": len(persisted.fact_ids),
        }

    graph = StateGraph(ChangeHistoryState)
    graph.add_node("prepare", prepare)
    graph.add_node("supervisor", supervisor)
    graph.add_node("diff", diff)
    graph.add_node("compose", compose)
    graph.add_node("impact", impact)
    graph.add_node("validate", validate)
    graph.add_node("assemble", assemble)
    graph.add_node("store", store)
    graph.set_entry_point("prepare")
    graph.add_edge("prepare", "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "diff": "diff",
            "compose": "compose",
            "impact": "impact",
            "validate": "validate",
            "assemble": "assemble",
        },
    )
    # 워커는 판단을 하지 않는다. 끝나면 항상 Supervisor로 돌아가 다음 경로를 받는다.
    graph.add_edge("diff", "supervisor")
    graph.add_edge("compose", "supervisor")
    graph.add_edge("impact", "supervisor")
    graph.add_edge("validate", "supervisor")
    graph.add_edge("assemble", "store")
    graph.add_edge("store", END)
    return graph.compile()


def _correction_for(state: ChangeHistoryState, worker: str) -> str:
    """검증이 남긴 사유를 그 워커에게 줄 교정 지시로 바꾼다.

    사유가 없으면(첫 재작업이 검증 실패가 아니라 호출 실패 때문이면) 빈 문자열을
    돌려준다 — 없는 문제를 고치라고 지시하면 오히려 결과가 나빠진다.
    """
    validation = state.get("validation")
    if not isinstance(validation, ValidationOutcome):
        return ""
    for problem in validation.problems:
        if problem.worker == worker and problem.reason in _CORRECTION_BY_REASON:
            return _CORRECTION_BY_REASON[problem.reason]
    return ""


def _accumulate_tokens(state: ChangeHistoryState, outcome: Any) -> dict[str, int]:
    """워커가 쓴 토큰을 상태의 누적값에 더한다.

    재작업이 일어나면 같은 워커가 두 번 도는데, 그 비용까지 합쳐야 실제로 든
    값이 남는다(벤치마크 비용 기록의 분모다).
    """
    return {
        "input_tokens": int(state.get("input_tokens") or 0)
        + int(getattr(outcome, "input_tokens", 0) or 0),
        "output_tokens": int(state.get("output_tokens") or 0)
        + int(getattr(outcome, "output_tokens", 0) or 0),
    }


def _state_reference_date(state: ChangeHistoryState) -> date:
    """상태에 담긴 기준일을 date로 꺼낸다. 없으면 서비스 시간대 기준 오늘."""
    value = state.get("reference_date")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return current_reference_date()


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def chg_001(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
    topic: str,
    contexts: list[Any],
    model: str = "gpt-4.1-mini",
    reference_date: date | None = None,
    db_lock: Any | None = None,
) -> dict[str, Any]:
    """[CHG-001] 변경점 추적 오케스트레이션.

    변경점 추적 서브그래프를 실행하고, 조립된 보고서와 실행 요약을 반환한다.
    기준일은 하드코딩하지 않고 인자로 주입받는다(테스트가 "오늘"에 흔들리지
    않게 하기 위함이다).

    Args:
        connection: 델타 테이블 조회·저장에 사용할 DB 연결
        user_id: 대상 사용자 식별자
        job_id: 실행을 유발한 Agent Job 식별자
        topic: 보고서 주제
        contexts: report_builder가 만든 오늘의 근거 문서
        model: 워커가 사용할 기본 모델
        reference_date: 절대 날짜 정형화 기준일. 생략하면 서비스 시간대 기준 오늘
        db_lock: 병렬 실행 시 DB 트랜잭션 충돌 방지용 동기화 락

    Returns:
        조립된 보고서(generated)와 실행 요약(팩트 수·드롭 플래그 등)
    """
    graph = build_change_history_graph(connection, db_lock=db_lock)
    state = await graph.ainvoke(
        {
            "user_id": user_id,
            "job_id": job_id,
            "topic": topic,
            "model": model,
            "reference_date": reference_date or current_reference_date(),
            "contexts": list(contexts),
        },
        # 워커마다 Supervisor를 한 번씩 더 거치므로 최악의 경로(워커 2회 재작업)가
        # LangGraph 기본 상한(25)에 닿는다. 재작업 상한은 코드가 이미 막고 있으니
        # 여기서는 여유를 준다.
        {"recursion_limit": 40},
    )
    generated = state.get("generated")
    if not isinstance(generated, GeneratedReportContent):
        raise RuntimeError("변경점 추적 그래프가 보고서를 반환하지 않았습니다.")
    validation = state.get("validation")
    all_facts = validation.facts if isinstance(validation, ValidationOutcome) else ()
    # 이번에 달라진 점(신규·갱신)만 추린다. 유지(중복) 팩트는 validation.facts에
    # 섞여 있지만(인용 검증용) 호출자에게는 "몇 건이 바뀌었나"만 의미 있다.
    highlight_facts = tuple(
        item for item in all_facts if item.fact.verdict != DUPLICATE
    )
    return {
        "generated": generated,
        "run_id": str(state.get("run_id") or ""),
        "is_first_run": bool(state.get("is_first_run")),
        "no_change": bool(state.get("no_change")),
        "fact_count": len(highlight_facts),
        "duplicate_count": int(state.get("duplicate_count") or 0),
        "stored_fact_count": int(state.get("stored_fact_count") or 0),
        "dropped_flags": list(state.get("dropped_flags") or []),
        "quality_outcome": str(state.get("quality_outcome") or ""),
        # 워커별 실행 횟수. 1을 넘으면 검증에 걸려 재작업한 것이며, 그만큼 비용이
        # 늘었다는 뜻이다(벤치마크가 재작업 발생률을 이 값으로 잰다).
        "diff_attempts": int(state.get("diff_attempts") or 0),
        "compose_attempts": int(state.get("compose_attempts") or 0),
        "impact_attempts": int(state.get("impact_attempts") or 0),
        "input_tokens": int(state.get("input_tokens") or 0),
        "output_tokens": int(state.get("output_tokens") or 0),
        "facts": list(highlight_facts),
    }
