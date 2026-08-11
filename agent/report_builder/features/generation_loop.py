"""Report Builder 본문 생성 루프의 버전 라우팅과 LangGraph V2 구현.

V1 단일 그래프(`agent/graph.py`)를 호환 경로로 그대로 두고, V2는 주제마다
독립 서브그래프(조사 → 근거 배정 → 섹션 초안 → 섹션 검토 ⟲ 재작성 → 등급)를
돌린 뒤 조립·최종검토·저장으로 잇는다.

V1 대비 바뀌는 것은 **입도(granularity)** 다. V1은 리포트 전체를 한 덩어리로
생성하고 검토도 전체 단위로 한 번 되돌린다. 주제 3개 중 1개가 나빠도 전체를
다시 쓰거나 그대로 발행해야 했다. V2는 나쁜 섹션만 다시 쓴다.

계약 상세는 docs/report-generation-v2-rollout.md 를 따른다.
"""

from __future__ import annotations

import asyncio
import logging
import os
from asyncio import to_thread
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Any, NotRequired, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from psycopg import AsyncConnection

from agent.assistant.api import resolve_topic_intent
from domain.personal_wiki.retrieval.api import prag_007
from infrastructure.persistence.api import set_personal_wiki_scope
from shared.contracts import FeatureRequest
from shared.report_models import GeneratedReportContent, ReportContextDocument

from .critic import CriticVerdict, critic_enabled, review_report
from .events import report_020
from .generation import generate_report_content_with_quality
from .live_sources import select_generation_context
from .persistence import report_018
from .read_loop import LEGACY_READ_PIPELINE_VERSION, research_context_for_version
from .safeguards import report_021
from .topic_focus import focus_documents_on_topic

logger = logging.getLogger("agent.report_builder.generation_loop")

type DictRow = dict[str, Any]

LEGACY_GENERATION_PIPELINE_VERSION = "legacy_v1"
LANGGRAPH_GENERATION_PIPELINE_VERSION = "langgraph_v2"
GENERATION_PIPELINE_VERSIONS = frozenset(
    {
        LEGACY_GENERATION_PIPELINE_VERSION,
        LANGGRAPH_GENERATION_PIPELINE_VERSION,
    }
)

# 섹션 등급. 근거를 못 찾은 주제를 화면에서 지우지 않기 위한 3분류다.
GRADE_OK = "ok"
GRADE_THIN = "thin"
GRADE_NO_EVIDENCE = "no_evidence"

# 근거가 이 수 미만이면 초안이 나왔더라도 thin으로 표시한다. 발행을 막지는
# 않는다 — 사용자에게는 얕은 섹션이라도 없는 것보다 낫고, 등급은 관측용이다.
_THIN_EVIDENCE_FLOOR = 2


def _env_int(name: str, default: int) -> int:
    """정수 환경변수를 읽고, 값이 없거나 해석할 수 없으면 기본값을 쓴다."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning("환경변수 %s 값을 정수로 읽지 못해 기본값 %d을 씁니다.", name, default)
        return default


def default_generation_pipeline_version() -> str:
    """새 Job에 고정할 생성 루프 버전을 환경변수에서 읽는다.

    기본값은 `langgraph_v2`다(2026-08-12 우석 결정, rollout 문서 §2.1). 롤백은
    `GENERATION_PIPELINE_VERSION=legacy_v1`로 되돌린 뒤 새 Job부터 적용된다.
    이미 접수된 Job은 Payload에 고정된 버전으로 끝난다.
    """
    raw = (os.getenv("GENERATION_PIPELINE_VERSION") or "").strip()
    if raw in GENERATION_PIPELINE_VERSIONS:
        return raw
    if raw:
        logger.warning(
            "지원하지 않는 GENERATION_PIPELINE_VERSION=%s — 기본값을 사용합니다.", raw
        )
    return LANGGRAPH_GENERATION_PIPELINE_VERSION


def section_max_revisions() -> int:
    """섹션 하나를 다시 쓸 수 있는 최대 횟수."""
    return max(0, _env_int("GENERATION_SECTION_MAX_REVISIONS", 2))


def topic_concurrency() -> int:
    """주제 서브그래프를 동시에 몇 개까지 돌릴지."""
    return max(1, _env_int("GENERATION_TOPIC_CONCURRENCY", 3))


@dataclass(frozen=True, slots=True)
class GenerationRuntimeContext:
    """V2 생성 그래프 노드가 공유하는 실행 시점 DB 연결."""

    connection: AsyncConnection[DictRow]


class ReportSectionState(TypedDict):
    """주제 하나를 담당하는 섹션 서브그래프의 상태."""

    topic: str
    user_id: str
    job_id: str
    content_type: str
    language: str
    model: str
    read_pipeline_version: str
    wiki_version_id: NotRequired[str | None]
    navigation_snapshot: NotRequired[Mapping[str, object] | None]
    planned_queries: NotRequired[list[str]]
    interest_bundle: NotRequired[Mapping[str, object] | None]
    max_revisions: int
    # 아래는 노드가 채운다.
    topic_intent: NotRequired[str]
    documents: NotRequired[list[ReportContextDocument]]
    contexts: NotRequired[list[ReportContextDocument]]
    collected_live: NotRequired[bool]
    research_stat: NotRequired[dict[str, object]]
    content: NotRequired[GeneratedReportContent | None]
    correction: NotRequired[str]
    revisions: NotRequired[int]
    critique_outcome: NotRequired[str]
    critique_problem: NotRequired[str]
    grade: NotRequired[str]
    started_ms: NotRequired[float]
    section: NotRequired[dict[str, object]]


class ReportGenerationV2State(TypedDict):
    """주제별 섹션을 조립해 리포트 하나를 만드는 상위 그래프의 상태."""

    user_id: str
    job_id: str
    attempt_number: int
    topic: str
    topics: list[str]
    content_type: str
    language: str
    model: str
    read_pipeline_version: str
    wiki_version_id: NotRequired[str | None]
    wiki_navigation_snapshots: NotRequired[dict[str, dict[str, object]]]
    topic_interest_bundles: NotRequired[dict[str, dict[str, object]]]
    interest_bundle: NotRequired[dict[str, object]]
    generation_scope: NotRequired[str]
    # 아래는 노드가 채운다.
    planned_topics: NotRequired[list[str]]
    sections: NotRequired[list[dict[str, object]]]
    generated: NotRequired[GeneratedReportContent]
    contexts: NotRequired[list[ReportContextDocument]]
    latency_ms: NotRequired[int]
    review_outcome: NotRequired[str]
    review_problem: NotRequired[str]
    section_trace: NotRequired[list[dict[str, object]]]
    evidence_trace: NotRequired[list[dict[str, object]]]
    research_stats: NotRequired[list[dict[str, object]]]
    result: NotRequired[dict[str, object]]


def coverage_note(topic: str) -> str:
    """근거를 못 찾은 주제에 붙일 커버리지 노트를 만든다.

    **LLM을 부르지 않는다.** 이 문장에는 사실 주장이 하나도 없어야 하기
    때문이다. 근거 없는 주제를 조용히 지우면(V1) 사용자는 "3개 요청했는데
    2개 왔다"를 보고, 일반론으로 채우면 없는 사실을 지어낸다(V1 이전 실측).
    둘 다 피하려고 코드가 만든 고정 문구를 쓴다.
    """
    return (
        f"### {topic}\n\n"
        "이번 브리핑에서는 이 주제를 뒷받침할 새 근거를 찾지 못했습니다."
    )


def plan_report_topics(topic: str, topics: Sequence[str]) -> list[str]:
    """요청 주제를 섹션 목록으로 정리한다. 순서는 요청 그대로 유지한다.

    `topics`가 비면 `topic` 하나를 다루는 단일 주제 요청이다. `topics`가 있으면
    `topic`은 카드 제목·generation_topic 용도라 주제 목록에 넣지 않는다(V1 계약과
    동일). 중복은 합치되 표기는 처음 등장한 것을 남긴다 — 섹션 제목이 되기 때문이다.

    Args:
        topic: 요청 대표 주제
        topics: 한 리포트가 함께 다룰 주제 목록(비어 있을 수 있다)

    Returns:
        중복을 합친 주제 목록(요청 순서)

    Raises:
        ValueError: 정리 후 주제가 하나도 남지 않은 경우
    """
    requested = [str(item).strip() for item in topics if str(item).strip()]
    if not requested:
        requested = [str(topic).strip()]
    planned: list[str] = []
    seen: set[str] = set()
    for item in requested:
        marker = item.casefold()
        if not item or marker in seen:
            continue
        seen.add(marker)
        planned.append(item)
    if not planned:
        raise ValueError("생성할 주제가 없습니다.")
    return planned


def _section_payload(state: ReportSectionState) -> dict[str, object]:
    """섹션 서브그래프 결과를 상위 그래프가 읽을 형태로 만든다."""
    content = state.get("content")
    started = float(state.get("started_ms") or monotonic())
    return {
        "topic": state["topic"],
        "grade": str(state.get("grade") or GRADE_NO_EVIDENCE),
        "evidence_count": len(state.get("contexts") or []),
        "revisions": int(state.get("revisions") or 0),
        "critique_outcome": str(state.get("critique_outcome") or ""),
        "latency_ms": int((monotonic() - started) * 1000),
        "content": content,
        "contexts": list(state.get("contexts") or []),
        "collected_live": bool(state.get("collected_live")),
        "research_stat": dict(state.get("research_stat") or {}),
    }


def build_report_section_graph_v2() -> Any:
    """주제 하나를 조사·작성·검토·재작성하는 섹션 서브그래프를 컴파일한다."""

    async def research_topic(
        state: ReportSectionState,
        runtime: Runtime[GenerationRuntimeContext],
    ) -> dict[str, object]:
        """이 주제의 근거만 모은다.

        읽기 루프 버전(`read_pipeline_version`)은 Job에 고정된 값을 그대로
        넘긴다 — 생성 루프 V2는 읽기 V1·V2 어느 쪽과도 조합된다.

        **실패해도 예외를 올리지 않는다.** 한 주제의 조사 실패가 다른 주제나
        리포트 전체를 막으면 안 된다. 빈손으로 두면 assess_topic이 근거 없음
        경로로 보낸다.
        """
        started = monotonic()
        topic = state["topic"]
        intent = await to_thread(resolve_topic_intent, topic, state["user_id"])
        kwargs: dict[str, Any] = {
            "topic": topic,
            "user_id": state["user_id"],
            "topic_intent": intent,
            "model": state["model"],
            "wiki_version_id": state.get("wiki_version_id"),
            "job_id": state["job_id"],
        }
        snapshot = state.get("navigation_snapshot")
        if snapshot:
            kwargs["navigation_snapshot"] = snapshot
        planned = [item for item in (state.get("planned_queries") or []) if item]
        if planned:
            kwargs["planned_queries"] = planned
        try:
            outcome = await research_context_for_version(
                runtime.context.connection,
                pipeline_version=state["read_pipeline_version"],
                **kwargs,
            )
        except Exception:
            logger.exception("주제 조사에 실패했습니다(주제=%s) — 근거 없이 진행합니다.", topic)
            return {
                "topic_intent": intent,
                "documents": [],
                "collected_live": False,
                "started_ms": started,
                "research_stat": {"topic": topic, "failed": True},
            }
        return {
            "topic_intent": intent,
            "documents": list(outcome.documents),
            "collected_live": bool(outcome.collected_live),
            "started_ms": started,
            "research_stat": {
                "topic": topic,
                "documents": len(outcome.documents),
                "stop_reason": outcome.stop_reason,
                "collected_live": bool(outcome.collected_live),
                "input_tokens": outcome.input_tokens,
                "output_tokens": outcome.output_tokens,
            },
        }

    async def assess_topic(state: ReportSectionState) -> dict[str, object]:
        """모은 근거를 주제에 좁히고 생성에 넣을 몫으로 추린다.

        `focus_documents_on_topic`은 실패하면 원본을 그대로 돌려주므로 여기서
        근거가 통째로 사라지지 않는다. 성공했는데 남은 문장이 없는 문서만
        빠진다 — 무관한 근거로 섹션을 채우는 것을 막는다.
        """
        documents = list(state.get("documents") or [])
        if not documents:
            return {"contexts": []}
        focused = await to_thread(
            focus_documents_on_topic,
            state["topic"],
            documents,
            model=state["model"],
        )
        contexts = select_generation_context(focused, [])
        return {"contexts": contexts}

    def route_after_assess(state: ReportSectionState) -> str:
        """근거가 하나도 없으면 초안을 만들지 않고 등급으로 간다."""
        return "draft_section" if state.get("contexts") else "grade_section"

    async def draft_section(state: ReportSectionState) -> dict[str, object]:
        """이 주제 몫의 섹션 하나를 생성한다.

        리포트 전체가 아니라 섹션이므로 프롬프트에 들어가는 근거 대비 본문
        비율이 높다. 무료 품질 검사(`generate_report_content_with_quality`)는
        그대로 태운다 — 글자 수·인용 형식 같은 코드 판정은 LLM 호출 없이 끝난다.
        """
        contexts = list(state.get("contexts") or [])
        try:
            content = await to_thread(
                generate_report_content_with_quality,
                topic=state["topic"],
                content_type=state["content_type"],
                language=state["language"],
                contexts=contexts,
                model=state["model"],
                correction=str(state.get("correction") or ""),
                interest_bundle=state.get("interest_bundle"),
            )
        except Exception:
            logger.exception("섹션 생성에 실패했습니다(주제=%s).", state["topic"])
            return {"content": None, "correction": ""}
        return {"content": content, "correction": ""}

    async def critique_section(
        state: ReportSectionState,
        runtime: Runtime[GenerationRuntimeContext],
    ) -> dict[str, object]:
        """이 섹션의 인용만 원문과 대조한다.

        검토가 불가능하면(스위치 꺼짐·LLM 장애·응답 파손) 통과시킨다. 검토는
        품질을 높이는 장치지 발행을 막는 관문이 아니다(V1과 같은 원칙).
        """
        content = state.get("content")
        if content is None:
            return {"critique_outcome": "unavailable", "correction": ""}
        if not critic_enabled():
            return {"critique_outcome": "disabled", "correction": ""}
        verdict: CriticVerdict = await review_report(
            runtime.context.connection,
            content=content,
            contexts=list(state.get("contexts") or []),
            user_id=state["user_id"],
            topic=state["topic"],
            topic_intent=str(state.get("topic_intent") or "news"),
            model=state["model"],
        )
        return {
            "critique_outcome": verdict.outcome,
            "critique_problem": verdict.problem,
            "correction": verdict.correction if verdict.should_regenerate else "",
        }

    def route_after_critique(state: ReportSectionState) -> str:
        """지적이 있고 재작성 상한이 남았으면 그 섹션만 다시 쓴다."""
        if not state.get("correction"):
            return "grade_section"
        if int(state.get("revisions") or 0) >= int(state["max_revisions"]):
            logger.info(
                "섹션 재작성 상한에 도달해 그대로 발행합니다(주제=%s).", state["topic"]
            )
            return "grade_section"
        return "revise_section"

    async def revise_section(state: ReportSectionState) -> dict[str, object]:
        """검토 지적을 교정 지시로 붙여 이 섹션만 다시 쓴다."""
        revisions = int(state.get("revisions") or 0) + 1
        drafted = await draft_section(state)
        # 재작성이 실패하면 직전 초안을 잃지 않는다 — 있는 것으로 발행한다.
        content = drafted.get("content") or state.get("content")
        return {"content": content, "correction": "", "revisions": revisions}

    async def grade_section(state: ReportSectionState) -> dict[str, object]:
        """섹션에 최종 등급을 붙이고 상위 그래프가 읽을 결과를 만든다."""
        content = state.get("content")
        evidence = len(state.get("contexts") or [])
        if content is None or evidence == 0:
            grade = GRADE_NO_EVIDENCE
        elif evidence < _THIN_EVIDENCE_FLOOR:
            grade = GRADE_THIN
        else:
            grade = GRADE_OK
        graded: ReportSectionState = {**state, "grade": grade}  # type: ignore[typeddict-item]
        return {"grade": grade, "section": _section_payload(graded)}

    graph = StateGraph(ReportSectionState, context_schema=GenerationRuntimeContext)
    graph.add_node("research_topic", research_topic)
    graph.add_node("assess_topic", assess_topic)
    graph.add_node("draft_section", draft_section)
    graph.add_node("critique_section", critique_section)
    graph.add_node("revise_section", revise_section)
    graph.add_node("grade_section", grade_section)
    graph.set_entry_point("research_topic")
    graph.add_edge("research_topic", "assess_topic")
    graph.add_conditional_edges(
        "assess_topic",
        route_after_assess,
        {"draft_section": "draft_section", "grade_section": "grade_section"},
    )
    graph.add_edge("draft_section", "critique_section")
    graph.add_conditional_edges(
        "critique_section",
        route_after_critique,
        {"revise_section": "revise_section", "grade_section": "grade_section"},
    )
    graph.add_edge("revise_section", "critique_section")
    graph.add_edge("grade_section", END)
    return graph.compile()


def assemble_sections(
    sections: Sequence[Mapping[str, object]],
    *,
    fallback_topic: str,
) -> tuple[GeneratedReportContent, list[ReportContextDocument]]:
    """주제별 섹션을 리포트 하나로 합친다. **LLM을 부르지 않는다.**

    합치는 단계에서 다시 LLM을 부르면 주제별로 검증을 마친 문장이 또 흔들린다.
    제목·요약은 근거를 확보한 섹션에서만 가져오고, 근거 없는 주제는 지우지 않고
    커버리지 노트로 남긴다(rollout 문서 §3.2).

    Args:
        sections: 섹션 서브그래프 결과 목록(요청 주제 순서)
        fallback_topic: 섹션 제목이 하나도 없을 때 쓸 리포트 제목

    Returns:
        (조립된 리포트 콘텐츠, 인용 대조에 쓸 근거 문서 합집합)
    """
    body_blocks: list[str] = []
    summaries: list[str] = []
    titles: list[str] = []
    references: list[str] = []
    tags: list[str] = []
    contexts: list[ReportContextDocument] = []
    seen_references: set[str] = set()
    seen_contexts: set[str] = set()
    seen_tags: set[str] = set()

    for section in sections:
        topic = str(section.get("topic") or "").strip()
        content = section.get("content")
        if not isinstance(content, GeneratedReportContent):
            body_blocks.append(coverage_note(topic or fallback_topic))
            continue
        titles.append(content.title.strip())
        if content.summary.strip():
            summaries.append(content.summary.strip())
        body = content.body.strip()
        # 섹션 생성기가 제목을 붙이지 않으므로 주제 제목을 코드가 얹는다.
        # 이미 같은 제목으로 시작하면 중복해서 붙이지 않는다.
        heading = f"### {topic}" if topic else ""
        if heading and not body.startswith(heading):
            body = f"{heading}\n\n{body}"
        body_blocks.append(body)
        for reference in content.citation_references:
            if reference not in seen_references:
                seen_references.add(reference)
                references.append(reference)
        for tag in content.content_tags:
            marker = tag.strip().casefold()
            if tag.strip() and marker not in seen_tags:
                seen_tags.add(marker)
                tags.append(tag.strip())
        for document in section.get("contexts") or []:
            if not isinstance(document, ReportContextDocument):
                continue
            if document.reference in seen_contexts:
                continue
            seen_contexts.add(document.reference)
            contexts.append(document)

    covered_titles = [title for title in titles if title]
    if len(covered_titles) == 1:
        title = covered_titles[0]
    elif covered_titles:
        title = " · ".join(covered_titles[:3])
    else:
        title = fallback_topic
    generated = GeneratedReportContent(
        title=title,
        summary=" ".join(summaries).strip(),
        body="\n\n".join(block for block in body_blocks if block.strip()),
        citation_references=tuple(references),
        content_tags=tuple(tags),
    )
    return generated, contexts


def build_report_generation_graph_v2(connection: AsyncConnection[DictRow]) -> Any:
    """주제별 섹션을 조립해 리포트를 만드는 상위 그래프를 컴파일한다.

    plan_topics → run_sections(주제별 서브그래프 fan-out) → assemble →
    final_review → persist 순서다. 저장 계약은 V1과 **같은 함수**를 호출한다.
    """

    def plan_topics(state: ReportGenerationV2State) -> dict[str, object]:
        """요청 주제를 정리한다(순수 함수 `plan_report_topics` 위임)."""
        return {
            "planned_topics": plan_report_topics(
                state["topic"], state.get("topics") or []
            )
        }

    async def run_sections(state: ReportGenerationV2State) -> dict[str, object]:
        """주제마다 섹션 서브그래프를 동시에 돌린다.

        동시 실행 수는 `GENERATION_TOPIC_CONCURRENCY`로 제한한다. 한 주제가
        예외로 죽어도 나머지는 그대로 진행하고, 죽은 주제는 근거 없음 섹션이
        된다 — 한 주제의 실패가 리포트 전체를 막지 않는다.
        """
        section_graph = build_report_section_graph_v2()
        snapshots = state.get("wiki_navigation_snapshots") or {}
        bundles = state.get("topic_interest_bundles") or {}
        max_revisions = section_max_revisions()
        semaphore = asyncio.Semaphore(topic_concurrency())

        def _empty_section(topic: str, started: float, outcome: str) -> dict[str, object]:
            """근거를 확보하지 못한 주제의 섹션 결과를 만든다."""
            return {
                "topic": topic,
                "grade": GRADE_NO_EVIDENCE,
                "evidence_count": 0,
                "revisions": 0,
                "critique_outcome": outcome,
                "latency_ms": int((monotonic() - started) * 1000),
                "content": None,
                "contexts": [],
                "collected_live": False,
                "research_stat": {"topic": topic, "failed": outcome == "failed"},
            }

        async def run_one(topic: str) -> dict[str, object]:
            """주제 하나의 섹션 서브그래프를 실행하고 결과 Payload를 돌려준다."""
            async with semaphore:
                started = monotonic()
                try:
                    final = await section_graph.ainvoke(
                        {
                            "topic": topic,
                            "user_id": state["user_id"],
                            "job_id": state["job_id"],
                            "content_type": state["content_type"],
                            "language": state["language"],
                            "model": state["model"],
                            "read_pipeline_version": (
                                state.get("read_pipeline_version")
                                or LEGACY_READ_PIPELINE_VERSION
                            ),
                            "wiki_version_id": state.get("wiki_version_id"),
                            "navigation_snapshot": snapshots.get(topic),
                            "interest_bundle": (
                                bundles.get(topic) or state.get("interest_bundle") or None
                            ),
                            "max_revisions": max_revisions,
                        },
                        context=GenerationRuntimeContext(connection=connection),
                    )
                except Exception:
                    logger.exception("섹션 서브그래프가 실패했습니다(주제=%s).", topic)
                    return _empty_section(topic, started, "failed")
                section = final.get("section")
                if isinstance(section, dict):
                    return section
                return _empty_section(topic, started, "")

        planned = list(state.get("planned_topics") or [])
        sections = list(await asyncio.gather(*(run_one(topic) for topic in planned)))
        return {"sections": sections}

    def assemble(state: ReportGenerationV2State) -> dict[str, object]:
        """섹션을 리포트 하나로 합치고 관측용 Trace를 만든다."""
        started = monotonic()
        sections = list(state.get("sections") or [])
        generated, contexts = assemble_sections(sections, fallback_topic=state["topic"])
        section_trace = [
            {
                "topic": section.get("topic"),
                "grade": section.get("grade"),
                "evidence_count": section.get("evidence_count"),
                "revisions": section.get("revisions"),
                "critique_outcome": section.get("critique_outcome"),
                "latency_ms": section.get("latency_ms"),
            }
            for section in sections
        ]
        evidence_trace = [
            {
                "topic": section.get("topic"),
                "selected": section.get("evidence_count"),
                "grade": section.get("grade"),
            }
            for section in sections
        ]
        research_stats = [
            dict(section.get("research_stat") or {})
            for section in sections
            if section.get("research_stat")
        ]
        return {
            "generated": generated,
            "contexts": contexts,
            "latency_ms": int((monotonic() - started) * 1000),
            "section_trace": section_trace,
            "evidence_trace": evidence_trace,
            "research_stats": research_stats,
        }

    async def final_review(state: ReportGenerationV2State) -> dict[str, object]:
        """조립된 리포트를 한 번 더 검토하되 **재작성으로 돌아가지 않는다.**

        섹션 단위 재작성이 이미 끝났다. 여기서 전체를 되돌리면 V1의 문제(리포트
        전체 단위 재생성)가 그대로 돌아온다. 지적은 저장 결과에 남겨 발행 후
        확인할 수 있게 한다.
        """
        generated = state.get("generated")
        contexts = list(state.get("contexts") or [])
        if generated is None or not contexts or not critic_enabled():
            return {"review_outcome": "disabled", "review_problem": ""}
        verdict: CriticVerdict = await review_report(
            connection,
            content=generated,
            contexts=contexts,
            user_id=state["user_id"],
            topic=state["topic"],
            model=state["model"],
        )
        return {
            "review_outcome": verdict.outcome,
            "review_problem": verdict.problem,
        }

    async def persist(state: ReportGenerationV2State) -> dict[str, object]:
        """생성 Run·후보·Citation·Snapshot·Outbox를 저장 Transaction으로 기록한다.

        V1 persist와 **같은 함수 사슬**을 호출한다(prag_007 → REPORT-018 →
        REPORT-020 → REPORT-021). 저장 알고리즘을 복제하지 않는다.

        V2는 델타 경로를 다루지 않으므로 `change_history_used`는 항상 False다.
        """
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=state["user_id"])
            citations = await prag_007(
                connection,
                job_id=state["job_id"],
                user_id=state["user_id"],
                attempt_number=state.get("attempt_number", 1),
                content_type=state["content_type"],
                generated=state["generated"],
                contexts=state["contexts"],
                latency_ms=state["latency_ms"],
                review_outcome=str(state.get("review_outcome") or ""),
                review_problem=str(state.get("review_problem") or ""),
                change_history_used=False,
            )
            persisted = await report_018(
                FeatureRequest(
                    request_id=state["job_id"],
                    actor_id="report-generation-graph-v2",
                    user_id=state["user_id"],
                    payload={"implementation": lambda: dict(citations)},
                )
            )
        completed = await report_020(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph-v2",
                user_id=state["user_id"],
                payload={"implementation": lambda: dict(persisted.data)},
            )
        )
        safeguarded = await report_021(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph-v2",
                user_id=state["user_id"],
                payload={"implementation": lambda: dict(completed.data)},
            )
        )
        result = dict(safeguarded.data)
        result["generation_pipeline_version"] = LANGGRAPH_GENERATION_PIPELINE_VERSION
        for key in ("section_trace", "evidence_trace", "research_stats"):
            value = state.get(key)
            if value:
                result[key] = list(value)
        read_pipeline_version = str(
            state.get("read_pipeline_version") or LEGACY_READ_PIPELINE_VERSION
        )
        if read_pipeline_version != LEGACY_READ_PIPELINE_VERSION:
            result["read_pipeline_version"] = read_pipeline_version
        return {"result": result}

    graph = StateGraph(ReportGenerationV2State)
    graph.add_node("plan_topics", plan_topics)
    graph.add_node("run_sections", run_sections)
    graph.add_node("assemble", assemble)
    graph.add_node("final_review", final_review)
    graph.add_node("persist", persist)
    graph.set_entry_point("plan_topics")
    graph.add_edge("plan_topics", "run_sections")
    graph.add_edge("run_sections", "assemble")
    graph.add_edge("assemble", "final_review")
    graph.add_edge("final_review", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


async def run_report_generation_v2(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
    attempt_number: int,
    topic: str,
    topics: Sequence[str] = (),
    content_type: str,
    language: str,
    model: str = "gpt-4.1-mini",
    generation_scope: str = "SINGLE_TOPIC",
    interest_bundle: Mapping[str, object] | None = None,
    topic_interest_bundles: Mapping[str, Mapping[str, object]] | None = None,
    wiki_version_id: str | None = None,
    wiki_navigation_snapshots: Mapping[str, Mapping[str, object]] | None = None,
    read_pipeline_version: str = LEGACY_READ_PIPELINE_VERSION,
) -> dict[str, object]:
    """생성 루프 V2 그래프를 실행하고 저장 결과 Payload를 반환한다."""
    graph = build_report_generation_graph_v2(connection)
    state = await graph.ainvoke(
        {
            "user_id": user_id,
            "job_id": job_id,
            "attempt_number": attempt_number,
            "topic": topic,
            "topics": [str(item) for item in topics],
            "content_type": content_type,
            "language": language,
            "model": model,
            "read_pipeline_version": read_pipeline_version,
            "wiki_version_id": wiki_version_id,
            "wiki_navigation_snapshots": {
                str(key): dict(value)
                for key, value in (wiki_navigation_snapshots or {}).items()
            },
            "topic_interest_bundles": {
                str(key): dict(value)
                for key, value in (topic_interest_bundles or {}).items()
            },
            "interest_bundle": dict(interest_bundle or {}),
            "generation_scope": generation_scope,
        }
    )
    return dict(state["result"])
