"""변경점(Delta) 추적 서브그래프 — Supervisor + 워커 + 도구.

토글이 켜지면 기존 report_builder의 `generate` 노드를 **대체**한다(그 앞에
generate가 도는 게 아니다). 즉 여기서 쓰는 글은 아직 아무도 검증하지 않은
완전히 새 콘텐츠이며, 뒤에 오는 기존 review(Critic)에서 처음으로 검증받는다.

    prepare → supervisor ⇄ {diff, compose, impact, validate} → assemble → store

Supervisor는 순서대로 호출하는 라우터가 아니라 **상태를 보고 실제로 다른 경로를
택하는 판단 노드**다.

  ① Base 팩트가 없으면(첫 실행) Diff worker의 **과거 대조만** 생략한다.
     worker 자체를 건너뛰지 않는 이유는 구조화 출력 형식이 유지돼야 Compose
     입력과 델타 테이블 저장에 그대로 쓸 수 있기 때문이다.
  ② Diff 결과가 전부 중복이면 Compose·Impact를 건너뛰고 "변화 없음" 짧은
     보고서 경로로 간다(LLM 2콜 절약).
  ③ 검증 실패 시 전체 재시도가 아니라 문제가 난 워커만 1회 재작업시킨다.
     재작업 후에도 실패하면 무한 루프를 돌지 말고 해당 항목을 드롭 + 플래그를
     남기고 통과한다.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
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
from .config import impact_model
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

# "변화 없음" 보고서의 품질 판정값. 인용 0개가 정상인 경로라 기존 quality 검사를
# 적용하지 않는다는 뜻이며, "통과(pass)"와는 구분해서 남긴다.
QUALITY_SKIPPED_NO_CHANGE = "skipped_no_change"

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


def build_change_history_graph(connection: AsyncConnection[DictRow]) -> Any:
    """변경점 추적 서브그래프의 노드와 엣지를 조립해 컴파일된 그래프를 반환한다.

    prepare(Base 조회) → supervisor(판단) → diff/compose/impact/validate →
    assemble(조립, 코드) → store(델타 저장) 순으로 잇는다. Supervisor로 되돌아오는
    엣지가 있어, 워커 재작업과 "변화 없음" 단축 경로가 같은 판단 노드를 지난다.

    빌드 시점에는 connection을 사용하지 않고 노드 클로저만 구성하므로,
    /dev/graphs 레지스트리는 None 스텁으로 구조를 추출할 수 있다.
    """

    async def prepare(state: ChangeHistoryState) -> dict[str, Any]:
        """직전 보고서 맥락과 과거 팩트 유무를 한 조회 Transaction으로 읽는다.

        Base는 성격이 다른 두 갈래다. (a)맥락 요약은 직전 publish_snapshot에서,
        (b)구조화된 과거 팩트는 델타 테이블에서 온다. Overview는 (a)를 딛고
        쓰고, Diff는 (b)를 대조 대상으로 삼는다.
        """
        user_id = state["user_id"]
        topic = state["topic"]
        async with connection.transaction():
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

    def _writable_facts(state: ChangeHistoryState) -> list[DiffFact]:
        """중복을 뺀, 보고서에 쓸 팩트만 추린다."""
        return [
            fact
            for fact in (state.get("diff_facts") or [])
            if isinstance(fact, DiffFact) and fact.verdict != DUPLICATE
        ]

    async def supervisor(state: ChangeHistoryState) -> dict[str, Any]:
        """상태를 보고 다음에 어느 워커로 갈지 정한다.

        이 노드는 LLM을 부르지 않는다. 판단 근거가 "무엇이 이미 끝났는가",
        "무엇이 실패했는가", "재작업 예산이 남았는가"처럼 세는 문제라,
        코드가 정하는 편이 결정적이고 무료다.
        """
        if not state.get("diff_done"):
            return {"route": "diff"}

        facts = _writable_facts(state)
        if not facts:
            # ② 전부 중복이거나 뽑힌 팩트가 없다. Compose·Impact를 건너뛴다.
            logger.info("유의미한 변화 없음: topic=%s — 짧은 보고서 경로", state["topic"])
            return {"route": "assemble", "no_change": True}

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
        """Overview와 타임라인을 한 번의 LLM 호출로 만든다."""
        attempts = int(state.get("compose_attempts") or 0)
        correction = _correction_for(state, COMPOSE_WORKER) if attempts else ""
        outcome = await chg_003(
            topic=state["topic"],
            facts=_writable_facts(state),
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
        """정제된 팩트로 파급효과와 행동 지침을 추론한다."""
        attempts = int(state.get("impact_attempts") or 0)
        outcome = await chg_004(
            topic=state["topic"],
            facts=_writable_facts(state),
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
        """조립 전에 팩트 정합성·날짜 타당성·인용 마커를 코드로 검사한다."""
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
            facts=_writable_facts(state),
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
        """검증을 통과한 출력에 섹션 헤더를 붙여 하나의 markdown으로 잇는다.

        조립 뒤 기존 무료 품질 검사(quality.evaluate_report)를 그대로 적용한다.
        새 판정 규칙을 만들지 않고 재사용하는 것이다.

        단 **"변화 없음" 보고서에는 적용하지 않는다.** 그 경로는 쓸 팩트가 없어
        인용도 없는 것이 정상인데, quality는 인용 0개를 무조건 `no_citations`
        (재생성 대상)로 본다. 고칠 수 없는 실패를 매번 실패로 기록하면 로그와
        지표가 오염돼 진짜 문제를 못 찾는다. 검사를 건너뛰었다는 사실 자체를
        판정값으로 남겨, "통과"와 구분되게 한다.
        """
        validation = state.get("validation")
        facts = (
            validation.facts if isinstance(validation, ValidationOutcome) else ()
        )
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
            facts=facts,
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
            no_change=bool(state.get("no_change")),
        )
        if state.get("no_change"):
            quality_outcome = QUALITY_SKIPPED_NO_CHANGE
        else:
            quality_outcome = evaluate_report(
                generated, context_count=len(contexts)
            ).outcome
        logger.info(
            "델타 보고서 조립 완료: topic=%s 팩트 %d건 품질=%s",
            state["topic"],
            len(facts),
            quality_outcome,
        )
        return {"generated": generated, "quality_outcome": quality_outcome}

    async def store(state: ChangeHistoryState) -> dict[str, Any]:
        """이번 실행의 팩트와 실행 메타를 델타 테이블에 저장한다.

        **첫 실행도 예외 없이 저장한다.** 이 저장은 출력이 아니라 다음 실행의
        Base 재료다. 저장 실패가 이미 만들어진 보고서를 못 나가게 하면 안 되므로
        예외는 경고 로그로만 남긴다(다음 실행이 복구 경로다).
        """
        validation = state.get("validation")
        facts = (
            validation.facts if isinstance(validation, ValidationOutcome) else ()
        )
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
            for item in facts
        ]
        try:
            async with connection.transaction():
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
    """상태에 담긴 기준일을 date로 꺼낸다. 없으면 오늘(UTC)."""
    value = state.get("reference_date")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(UTC).date()


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
        reference_date: 절대 날짜 정형화 기준일. 생략하면 오늘(UTC)

    Returns:
        조립된 보고서(generated)와 실행 요약(팩트 수·드롭 플래그 등)
    """
    graph = build_change_history_graph(connection)
    state = await graph.ainvoke(
        {
            "user_id": user_id,
            "job_id": job_id,
            "topic": topic,
            "model": model,
            "reference_date": reference_date or datetime.now(UTC).date(),
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
    facts = validation.facts if isinstance(validation, ValidationOutcome) else ()
    return {
        "generated": generated,
        "run_id": str(state.get("run_id") or ""),
        "is_first_run": bool(state.get("is_first_run")),
        "no_change": bool(state.get("no_change")),
        "fact_count": len(facts),
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
        "facts": list(facts),
    }
