"""Report Builder Wiki 읽기 루프의 버전 라우팅과 LangGraph V2 구현.

V1 Researcher Tool Loop를 호환 경로로 보존하면서, V2는 Wiki Locate·Seed 선택·
Navigation·Global 검색·충분성 판정·Live 보강을 명시적인 StateGraph 노드로 실행한다.
"""

from __future__ import annotations

import logging
import re
from asyncio import to_thread
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from time import monotonic
from typing import Any, NotRequired, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from psycopg import AsyncConnection

from domain.personal_wiki.navigation.api import wnav_001, wnav_006
from infrastructure.persistence.api import persist_report_navigation_snapshot
from shared.report_models import ReportContextDocument
from shared.wiki_navigation_models import (
    WikiNavigationCandidate,
    WikiNavigationPacket,
)
from shared.wiki_navigation_policy import (
    DEFAULT_WIKI_NAVIGATION_POLICY,
    WikiNavigationPolicy,
)

from .live_sources import collect_live_context
from .pool_context import is_pool_relevant, is_pool_sufficient
from .researcher import (
    ResearchOutcome,
    load_navigation_snapshot_packet,
    merge_context_documents,
    navigation_packet_documents,
    pool_documents_for_decision,
    research_context,
    search_global_documents,
)
from .wiki_retrieval import embed_wiki_queries

logger = logging.getLogger("agent.report_builder.read_loop")

type DictRow = dict[str, Any]

LEGACY_READ_PIPELINE_VERSION = "legacy_v1"
LANGGRAPH_READ_PIPELINE_VERSION = "langgraph_v2"
READ_PIPELINE_VERSIONS = frozenset(
    {LEGACY_READ_PIPELINE_VERSION, LANGGRAPH_READ_PIPELINE_VERSION}
)

_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")
_SEED_LIMIT = 3
_KOREAN_PARTICLES = (
    "으로",
    "에서",
    "에게",
    "까지",
    "부터",
    "처럼",
    "보다",
    "을",
    "를",
    "은",
    "는",
    "이",
    "가",
    "과",
    "와",
    "의",
    "에",
    "로",
    "도",
    "만",
)
_GENERIC_TOKENS = frozenset(
    {"관련", "메모", "내용", "자료", "찾아줘", "알려줘", "정리해줘", "저장한"}
)
_QUERY_SYNONYMS = {
    "변화": {"변경", "교체"},
    "변경": {"변화", "교체"},
    "교체": {"변화", "변경"},
}


@dataclass(frozen=True, slots=True)
class WikiReadRuntimeContext:
    """V2 읽기 그래프 노드가 공유하는 실행 시점 DB 연결."""

    connection: AsyncConnection[DictRow]


class WikiReadLoopState(TypedDict):
    """LangGraph Wiki 읽기 루프 V2가 노드 사이에서 갱신하는 상태."""

    topic: str
    user_id: str
    topic_intent: str
    model: str
    planned_queries: list[str]
    planned_wiki_version_ids: list[str]
    wiki_version_id: str | None
    job_id: str | None
    navigation_snapshot: Mapping[str, object] | None
    defer_live: bool
    navigation_policy: WikiNavigationPolicy
    normalized_queries: NotRequired[list[str]]
    candidates: NotRequired[list[WikiNavigationCandidate]]
    selected_version_ids: NotRequired[list[str]]
    packet: NotRequired[WikiNavigationPacket | None]
    global_documents: NotRequired[list[ReportContextDocument]]
    live_documents: NotRequired[list[ReportContextDocument]]
    collected_live: NotRequired[bool]
    pool_sufficient: NotRequired[bool]
    pool_relevant: NotRequired[bool]
    node_stats: NotRequired[list[tuple[str, int, int]]]
    outcome: NotRequired[ResearchOutcome]


def _normalized_tokens(value: str) -> set[str]:
    """후보 관련성 비교에 쓸 영문·숫자·한글 토큰 집합을 만든다."""
    normalized: set[str] = set()
    for raw_token in _TOKEN_PATTERN.findall(value):
        token = raw_token.casefold()
        for particle in _KOREAN_PARTICLES:
            if token.endswith(particle) and len(token) > len(particle) + 1:
                token = token[: -len(particle)]
                break
        if len(token) >= 2 and token not in _GENERIC_TOKENS:
            normalized.add(token)
    return normalized


def _candidate_relevance(
    topic: str, candidate: WikiNavigationCandidate
) -> tuple[float, float]:
    """질문과 후보 제목·별칭·요약의 결정적 관련성 점수와 RRF 점수를 반환한다."""
    normalized_topic = topic.casefold()
    surfaces = [candidate.title, *candidate.aliases]
    if candidate.exact_match:
        score = 100.0
    elif candidate.alias_match:
        score = 90.0
    elif any(surface.casefold() in normalized_topic for surface in surfaces if surface):
        score = 50.0
    else:
        query_tokens = _normalized_tokens(topic)
        expanded_query_tokens = set(query_tokens)
        for token in query_tokens:
            expanded_query_tokens.update(_QUERY_SYNONYMS.get(token, ()))
        title_tokens = _normalized_tokens(
            " ".join([candidate.title, *candidate.aliases])
        )
        summary_tokens = _normalized_tokens(candidate.summary)
        score = float(
            2 * len(expanded_query_tokens & title_tokens)
            + len(expanded_query_tokens & summary_tokens)
        )
        if score == 0 and candidate.vector_score is not None:
            score = (
                candidate.vector_score * 2.0
                if candidate.vector_score >= 0.55
                else 0.0
            )
    return score, candidate.rrf_score


def select_wiki_seed_candidates(
    topic: str,
    candidates: Sequence[WikiNavigationCandidate],
    *,
    limit: int = _SEED_LIMIT,
) -> list[WikiNavigationCandidate]:
    """질문 관련성과 RRF 순위로 최대 limit개의 Wiki Seed를 결정적으로 고른다."""
    if limit < 1:
        raise ValueError("Wiki Seed 후보 상한은 1 이상이어야 합니다.")
    ranked = [
        (candidate, _candidate_relevance(topic, candidate))
        for candidate in candidates
    ]
    ordered = sorted(
        ranked,
        key=lambda item: (item[1][0], item[1][1]),
        reverse=True,
    )
    direct = [candidate for candidate, (relevance, _rrf) in ordered if relevance >= 50]
    if direct:
        return direct[:limit]
    best_relevance = ordered[0][1][0] if ordered else 0.0
    selected = [
        candidate
        for candidate, (relevance, _rrf) in ordered
        if relevance > 0 and relevance > best_relevance * 0.5
    ]
    return selected[:limit]


def _append_stat(
    state: WikiReadLoopState, *, node: str, started: float, calls: int = 1
) -> list[tuple[str, int, int]]:
    """노드 호출 수와 경과 시간을 기존 실행 통계 뒤에 추가한다."""
    return [
        *(state.get("node_stats") or []),
        (node, calls, int((monotonic() - started) * 1000)),
    ]


def build_wiki_read_graph_v2() -> Any:
    """Wiki 읽기 루프 V2의 명시적인 LangGraph 노드와 분기를 컴파일한다."""

    async def restore_or_locate(
        state: WikiReadLoopState,
        runtime: Runtime[WikiReadRuntimeContext],
    ) -> dict[str, object]:
        """고정 Snapshot·Seed를 복원하거나 현재 고정 Wiki에서 후보를 찾는다."""
        started = monotonic()
        seen = {state["topic"].strip().casefold()}
        queries: list[str] = []
        for raw_query in state["planned_queries"]:
            query = str(raw_query).strip()
            marker = query.casefold()
            if not query or marker in seen:
                continue
            seen.add(marker)
            queries.append(query)
        selected_versions = list(
            dict.fromkeys(
                version_id.strip()
                for version_id in state["planned_wiki_version_ids"]
                if version_id.strip()
            )
        )[: state["navigation_policy"].budget.max_seed_pages]
        packet: WikiNavigationPacket | None = None
        candidates: list[WikiNavigationCandidate] = []
        if state["navigation_snapshot"]:
            packet = await load_navigation_snapshot_packet(
                runtime.context.connection,
                user_id=state["user_id"],
                topic=state["topic"],
                snapshot=state["navigation_snapshot"],
            )
        elif selected_versions:
            packet = await wnav_006(
                runtime.context.connection,
                user_id=state["user_id"],
                query=state["topic"],
                selected_document_version_ids=selected_versions,
                wiki_version_id=state["wiki_version_id"],
                max_depth=state["navigation_policy"].budget.max_depth,
                max_seed_pages=state["navigation_policy"].budget.max_seed_pages,
                max_pages=state["navigation_policy"].budget.max_pages,
                max_chunks=state["navigation_policy"].budget.max_chunks,
                hop_page_limits=(
                    state["navigation_policy"].budget.hop_page_limits
                ),
            )
        else:
            query_embedding: Sequence[float] | None = None
            try:
                embeddings = await to_thread(embed_wiki_queries, [state["topic"]])
                query_embedding = embeddings.get(state["topic"].strip())
            except Exception as error:  # noqa: BLE001 - Keyword Locate로 폴백한다
                logger.warning("V2 Wiki 임베딩 실패, Keyword Locate로 폴백: %s", error)
            candidates = await wnav_001(
                runtime.context.connection,
                user_id=state["user_id"],
                query=state["topic"],
                wiki_version_id=state["wiki_version_id"],
                limit=30,
                query_embedding=query_embedding,
            )
        return {
            "normalized_queries": queries,
            "selected_version_ids": selected_versions,
            "candidates": candidates,
            "packet": packet,
            "node_stats": _append_stat(
                state, node="restore_or_locate", started=started
            ),
        }

    async def select_seed(state: WikiReadLoopState) -> dict[str, object]:
        """복원된 Packet이 없을 때 Locate 후보에서 Seed Version을 결정적으로 고른다."""
        started = monotonic()
        selected = list(state.get("selected_version_ids") or [])
        if state.get("packet") is None and not selected:
            selected = [
                candidate.document_version_id
                for candidate in select_wiki_seed_candidates(
                    state["topic"],
                    state.get("candidates") or [],
                    limit=min(
                        _SEED_LIMIT,
                        state["navigation_policy"].budget.max_seed_pages,
                    ),
                )
            ]
        return {
            "selected_version_ids": selected,
            "node_stats": _append_stat(state, node="select_seed", started=started),
        }

    async def navigate(
        state: WikiReadLoopState,
        runtime: Runtime[WikiReadRuntimeContext],
    ) -> dict[str, object]:
        """선택한 Wiki Page Version과 검증 관계·Source를 Context Packet으로 읽는다."""
        started = monotonic()
        packet = state.get("packet")
        selected = state.get("selected_version_ids") or []
        if packet is None and selected:
            packet = await wnav_006(
                runtime.context.connection,
                user_id=state["user_id"],
                query=state["topic"],
                selected_document_version_ids=selected,
                candidates=tuple(state.get("candidates") or ()),
                wiki_version_id=state["wiki_version_id"],
                max_depth=state["navigation_policy"].budget.max_depth,
                max_seed_pages=state["navigation_policy"].budget.max_seed_pages,
                max_pages=state["navigation_policy"].budget.max_pages,
                max_chunks=state["navigation_policy"].budget.max_chunks,
                hop_page_limits=(
                    state["navigation_policy"].budget.hop_page_limits
                ),
            )
        return {
            "packet": packet,
            "node_stats": _append_stat(state, node="navigate", started=started),
        }

    async def search_global(
        state: WikiReadLoopState,
        runtime: Runtime[WikiReadRuntimeContext],
    ) -> dict[str, object]:
        """대표 주제와 접수 시 고정된 연관어로 Global 저장 근거를 조회한다."""
        started = monotonic()
        groups: list[Sequence[ReportContextDocument]] = []
        queries = [state["topic"], *(state.get("normalized_queries") or [])]
        for query in queries:
            groups.append(
                await search_global_documents(
                    runtime.context.connection,
                    user_id=state["user_id"],
                    query=query,
                    topic_intent=state["topic_intent"],
                )
            )
        documents = merge_context_documents(*groups)
        return {
            "global_documents": documents,
            "node_stats": _append_stat(
                state,
                node="search_global",
                started=started,
                calls=len(queries),
            ),
        }

    async def assess(state: WikiReadLoopState) -> dict[str, object]:
        """Global 근거의 개수와 주제 관련성을 결정적으로 판정한다."""
        started = monotonic()
        decision_pool = pool_documents_for_decision(
            state.get("global_documents") or []
        )
        try:
            relevant = await to_thread(
                is_pool_relevant, state["topic"], decision_pool
            )
        except Exception:  # noqa: BLE001 - 불확실하면 Live 보강 쪽으로 보낸다
            logger.exception("V2 Global 관련성 판정 실패, Live 보강을 시도합니다.")
            relevant = False
        sufficient = is_pool_sufficient(decision_pool)
        return {
            "pool_relevant": relevant,
            "pool_sufficient": sufficient,
            "node_stats": _append_stat(state, node="assess", started=started),
        }

    def route_after_assess(state: WikiReadLoopState) -> str:
        """근거가 충분하거나 상위에서 병렬 수집할 때 Live 노드를 건너뛴다."""
        return (
            "finalize"
            if (
                state.get("pool_sufficient") and state.get("pool_relevant")
            )
            or state["defer_live"]
            else "collect_live"
        )

    async def collect_live(state: WikiReadLoopState) -> dict[str, object]:
        """저장 근거가 부족할 때 기존 Live 수집기를 최대 한 번 실행한다."""
        started = monotonic()
        documents: list[ReportContextDocument] = []
        try:
            kwargs: dict[str, object] = {"model": state["model"]}
            if state.get("normalized_queries"):
                kwargs["related_keywords"] = state["normalized_queries"]
            documents = await to_thread(
                collect_live_context,
                state["topic"],
                state["user_id"],
                **kwargs,
            )
        except Exception:  # noqa: BLE001 - 확보한 Wiki·Global 근거는 보존한다
            logger.exception("V2 실시간 수집 실패, 저장 근거만 사용합니다.")
        return {
            "live_documents": documents,
            "collected_live": True,
            "node_stats": _append_stat(
                state, node="collect_live", started=started
            ),
        }

    async def finalize(
        state: WikiReadLoopState,
        runtime: Runtime[WikiReadRuntimeContext],
    ) -> dict[str, object]:
        """Wiki·Global·Live 근거를 합치고 Navigation Snapshot과 Trace를 확정한다."""
        started = monotonic()
        packet = state.get("packet")
        wiki_documents = (
            navigation_packet_documents(packet, user_id=state["user_id"])
            if packet is not None
            else []
        )
        documents = merge_context_documents(
            wiki_documents,
            state.get("global_documents") or [],
            state.get("live_documents") or [],
        )
        if packet is not None:
            hop_counts: dict[int, int] = {}
            for page in packet.pages:
                hop_counts[page.hops] = hop_counts.get(page.hops, 0) + 1
            logger.info(
                "event=wiki_navigation_completed user_id=%s query_hash=%s "
                "profile=%s hop_page_counts=%s relation_count=%d truncated=%s "
                "fallback_reason=%s context_document_count=%d",
                state["user_id"],
                sha256(state["topic"].strip().encode("utf-8")).hexdigest()[:16],
                state["navigation_policy"].profile,
                hop_counts,
                len(packet.relations),
                packet.truncated,
                packet.fallback_reason or "-",
                len(wiki_documents),
            )
        if (
            state["job_id"]
            and packet is not None
            and state["navigation_snapshot"] is None
        ):
            await persist_report_navigation_snapshot(
                runtime.context.connection,
                user_id=state["user_id"],
                job_id=state["job_id"],
                topic=state["topic"],
                packets=[packet],
            )
        stats = _append_stat(state, node="finalize", started=started)
        requires_live = not (
            state.get("pool_sufficient") and state.get("pool_relevant")
        ) and not state.get("collected_live")
        return {
            "node_stats": stats,
            "outcome": ResearchOutcome(
                documents=tuple(documents),
                notes=(
                    "LangGraph V2가 Wiki·Global·Live 근거를 명시적 단계로 수집했습니다."
                ),
                stop_reason=LANGGRAPH_READ_PIPELINE_VERSION,
                collected_live=bool(state.get("collected_live")),
                requires_live=requires_live,
                wiki_packets=(packet,) if packet is not None else (),
                tool_stats=tuple(stats),
            ),
        }

    graph = StateGraph(
        WikiReadLoopState,
        context_schema=WikiReadRuntimeContext,
    )
    graph.add_node("restore_or_locate", restore_or_locate)
    graph.add_node("select_seed", select_seed)
    graph.add_node("navigate", navigate)
    graph.add_node("search_global", search_global)
    graph.add_node("assess", assess)
    graph.add_node("collect_live", collect_live)
    graph.add_node("finalize", finalize)
    graph.set_entry_point("restore_or_locate")
    graph.add_edge("restore_or_locate", "select_seed")
    graph.add_edge("select_seed", "navigate")
    graph.add_edge("navigate", "search_global")
    graph.add_edge("search_global", "assess")
    graph.add_conditional_edges(
        "assess",
        route_after_assess,
        {"collect_live": "collect_live", "finalize": "finalize"},
    )
    graph.add_edge("collect_live", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


async def run_wiki_read_graph_v2(
    connection: AsyncConnection[DictRow],
    *,
    topic: str,
    user_id: str,
    topic_intent: str = "news",
    model: str = "gpt-4.1-mini",
    planned_queries: Sequence[str] = (),
    planned_wiki_version_ids: Sequence[str] = (),
    wiki_version_id: str | None = None,
    job_id: str | None = None,
    navigation_snapshot: Mapping[str, object] | None = None,
    defer_live: bool = False,
    navigation_policy: WikiNavigationPolicy = DEFAULT_WIKI_NAVIGATION_POLICY,
) -> ResearchOutcome:
    """Wiki 읽기 V2를 실행하고 선택적으로 Live 보강을 상위 병렬 단계로 미룬다."""
    graph = build_wiki_read_graph_v2()
    final = await graph.ainvoke(
        {
            "topic": topic,
            "user_id": user_id,
            "topic_intent": topic_intent,
            "model": model,
            "planned_queries": list(planned_queries),
            "planned_wiki_version_ids": list(planned_wiki_version_ids),
            "wiki_version_id": wiki_version_id,
            "job_id": job_id,
            "navigation_snapshot": navigation_snapshot,
            "defer_live": defer_live,
            "navigation_policy": navigation_policy,
        },
        context=WikiReadRuntimeContext(connection=connection),
    )
    outcome = final.get("outcome")
    if not isinstance(outcome, ResearchOutcome):
        raise RuntimeError("Wiki 읽기 V2 그래프가 조사 결과를 반환하지 않았습니다.")
    return outcome


async def research_context_for_version(
    connection: AsyncConnection[DictRow],
    *,
    pipeline_version: str = LEGACY_READ_PIPELINE_VERSION,
    topic: str,
    user_id: str,
    topic_intent: str = "news",
    model: str = "gpt-4.1-mini",
    max_iterations: int = 3,
    planned_queries: Sequence[str] = (),
    planned_wiki_version_ids: Sequence[str] = (),
    wiki_version_id: str | None = None,
    job_id: str | None = None,
    navigation_snapshot: Mapping[str, object] | None = None,
    defer_live: bool = False,
    navigation_policy: WikiNavigationPolicy = DEFAULT_WIKI_NAVIGATION_POLICY,
) -> ResearchOutcome:
    """Job에 고정된 버전에 따라 V1 Researcher 또는 LangGraph V2를 실행한다."""
    if pipeline_version == LEGACY_READ_PIPELINE_VERSION:
        return await research_context(
            connection,
            topic=topic,
            user_id=user_id,
            topic_intent=topic_intent,
            model=model,
            max_iterations=max_iterations,
            planned_queries=planned_queries,
            planned_wiki_version_ids=planned_wiki_version_ids,
            wiki_version_id=wiki_version_id,
            job_id=job_id,
            navigation_snapshot=navigation_snapshot,
            navigation_policy=navigation_policy,
        )
    if pipeline_version == LANGGRAPH_READ_PIPELINE_VERSION:
        return await run_wiki_read_graph_v2(
            connection,
            topic=topic,
            user_id=user_id,
            topic_intent=topic_intent,
            model=model,
            planned_queries=planned_queries,
            planned_wiki_version_ids=planned_wiki_version_ids,
            wiki_version_id=wiki_version_id,
            job_id=job_id,
            navigation_snapshot=navigation_snapshot,
            defer_live=defer_live,
            navigation_policy=navigation_policy,
        )
    raise ValueError(f"지원하지 않는 Wiki 읽기 파이프라인 버전입니다: {pipeline_version}")
