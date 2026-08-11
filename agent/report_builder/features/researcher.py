"""자료 조사 에이전트(Researcher).

리포트 근거 자료를 모으는 일을 **LLM이 스스로 판단해** 수행한다. 어떤 도구를
어떤 검색어로 몇 번 부를지 코드가 정하지 않는다 — 도구 목록과 원칙만 주고
LLM이 관찰 결과를 보며 다음 행동을 정한다.

기존 `load_context`는 "풀 검색 → 부족하면 수집"을 고정 순서로 실행했다. 이
모듈은 같은 재료(풀 검색·실시간 수집)를 **도구로 노출**해 LLM이 고르게 한다.
그 결과 토픽어 하나에 묶이지 않고, 관찰에서 발견한 연관 키워드로 검색을
넓힐 수 있다.

판단만 LLM에게 넘기고 **점수 계산·신선도 컷오프는 결정론으로 남긴다** —
도구 안쪽은 기존 `pool_context`·`live_sources` 규칙을 그대로 쓴다.
"""

from __future__ import annotations

import logging
import os
import re
from asyncio import to_thread
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

from psycopg import AsyncConnection

from time import monotonic

from agent.llm.api import ToolCallRecord, ToolSpec, run_tool_loop
from domain.personal_wiki.navigation.api import (
    wnav_001,
    wnav_002,
    wnav_005,
    wnav_006,
)
from domain.personal_wiki.retrieval.api import prag_003
from infrastructure.persistence.api import (
    load_global_document_freshness,
    load_global_report_context,
    persist_report_navigation_snapshot,
    set_personal_wiki_scope,
)
from shared.report_models import ReportContextDocument
from shared.wiki_navigation_models import (
    WikiNavigationCandidate,
    WikiNavigationPacket,
    WikiNavigationRelation,
    WikiNavigationRelationSupport,
    WikiNavigationSource,
)

from .live_sources import collect_live_context
from .pool_context import (
    GLOBAL_NAMESPACE,
    is_pool_relevant,
    is_pool_sufficient,
    select_personal_documents,
    select_pool_documents,
)
from .wiki_retrieval import embed_wiki_queries

logger = logging.getLogger("agent.report_builder.researcher")

type DictRow = dict[str, Any]

RESEARCH_MAX_ITERATIONS = 5
_OBSERVATION_SNIPPET_CHARS = 160


# 조사원에게는 "무엇을 검색할까"만 맡긴다. "몇 건이면 충분한가"는 세는 문제라
# 코드(is_pool_sufficient)가 판정한다 — 2026-07-31 벤치마크에서 LLM에게 셈을
# 맡겼을 때 판단 정확도가 80%에 그쳤고, 프롬프트를 두 번 고쳐도 오류 방향만
# 바뀌었다.
SYSTEM_PROMPT = (
    "너는 리포트 작성에 쓸 근거 자료를 모으는 조사원이다.\n"
    "개인 Wiki는 wiki_search로 후보를 찾은 뒤 필요한 Version ID만 wiki_read로 "
    "읽고, 외부 저장 자료는 search_pool로 찾는다.\n"
    "다 모았으면 무엇을 모았는지 한 문단으로 요약한다.\n"
    "\n"
    "원칙:\n"
    "1. 주제어로 wiki_search를 먼저 호출하고 최대 30개 후보에서 질문에 직접 "
    "필요한 Page만 고른다. 연결 수나 후보 순위만 보고 고르지 마라.\n"
    "2. 고른 document_version_id를 최대 6개까지 한 번의 wiki_read로 읽는다. "
    "wiki_search 결과를 읽은 것으로 간주하지 마라.\n"
    "3. 최신 외부 사실이 필요하면 search_pool을 호출한다. 첫 결과에 주제와 "
    "밀접한 용어가 보이면 그 용어로 한두 번 더 자료를 넓힌다.\n"
    "4. 검색어를 바꿨는데 새로 나온 자료가 없으면 그 방향은 접는다.\n"
    "   비슷한 말로 바꿔 가며 같은 검색을 반복하지 마라.\n"
    "5. 주제와 무관한 자료가 나오면 그 검색어는 버리고 다른 검색어를 시도한다.\n"
    "6. 더 넓힐 방향이 없으면 그만 찾고 요약한다.\n"
)

FIXED_WIKI_SYSTEM_PROMPT = (
    "너는 리포트 작성에 쓸 근거 자료를 모으는 조사원이다.\n"
    "개인 Wiki Page·관계·Source는 이번 Job 요청 또는 첫 실행에서 이미 고정했다. "
    "고정 Context를 그대로 쓰고, 최신 외부 사실이 필요할 때만 "
    "search_pool로 Global 저장 자료를 찾는다.\n"
    "같은 검색을 비슷한 말로 반복하지 말고, 더 필요한 방향이 없으면 요약한다."
)


def research_agent_enabled() -> bool:
    """조사원 에이전트를 사용할지 환경변수로 확인한다.

    끄면 기존 고정 경로(풀 검색 → 부족하면 수집)로 되돌아간다. 조사원은 도구
    호출마다 LLM을 부르므로, 비용·지연을 비교하거나 장애 시 즉시 되돌리려면
    스위치가 필요하다. 기본값은 켬이다.
    """
    return os.getenv("RESEARCH_AGENT_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


@dataclass(frozen=True, slots=True)
class ResearchOutcome:
    """조사 결과로 모인 근거 문서와 실행 기록.

    Attributes:
        documents: 중복 제거된 근거 문서 목록
        calls: LLM이 실행한 도구 호출 기록(어떤 검색어를 왜 골랐는지 추적용)
        notes: LLM이 남긴 조사 요약
        stop_reason: 루프 종료 사유("final" 또는 "max_iterations")
        collected_live: 실시간 수집을 **시도했는지**. 성공 여부가 아니라 시도
            여부다 — 호출자(graph.load_context)가 같은 수집을 한 번 더
            돌리지 않도록 판단하는 데 쓴다.
        input_tokens·output_tokens: 조사에 쓴 토큰 (벤치마크 비용 기록용)
    """

    documents: tuple[ReportContextDocument, ...] = ()
    calls: tuple[ToolCallRecord, ...] = ()
    notes: str = ""
    stop_reason: str = "final"
    collected_live: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    wiki_packets: tuple[WikiNavigationPacket, ...] = ()
    # 도구별 (호출 수, 누적 ms). 조사 노드가 리포트 시간의 대부분을 쓰는데
    # 안이 안 보여 어디를 줄일지 판단할 수 없었다(2026-08-11, 이송우 협의).
    tool_stats: tuple[tuple[str, int, int], ...] = ()


@dataclass(slots=True)
class WikiNavigationSession:
    """한 Reader Tool Loop 안에서 후보와 읽은 Packet을 보존한다."""

    candidates: dict[str, WikiNavigationCandidate] = field(default_factory=dict)
    packets: list[WikiNavigationPacket] = field(default_factory=list)
    query: str = ""

    def remember_candidates(
        self, candidates: Sequence[WikiNavigationCandidate], *, query: str
    ) -> None:
        """Locate 후보를 Version ID로 조회할 수 있게 보관한다."""
        self.candidates = {
            candidate.document_version_id: candidate for candidate in candidates
        }
        self.query = query

    def remember_packet(self, packet: WikiNavigationPacket) -> None:
        """Reader가 실제로 읽은 Context Packet을 순서대로 보관한다."""
        self.packets.append(packet)


def _document_key(document: ReportContextDocument) -> str:
    """중복 판정에 쓸 문서 식별 키를 만든다."""
    if document.namespace_key != GLOBAL_NAMESPACE and document.document_version_id:
        return f"{document.namespace_key}:{document.document_version_id}"
    return document.url or f"{document.namespace_key}:{document.document_version_id}"


async def search_stored_documents(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    query: str,
    topic_intent: str = "news",
) -> list[ReportContextDocument]:
    """저장된 자료(개인 Wiki + Global 풀)를 검색해 쓸 만한 문서를 반환한다.

    조사원과 검토자가 함께 쓰는 검색 경계다. 풀 문서는 기존 신선도·점수 컷오프
    (select_pool_documents)를 적용하고, 개인 Wiki 문서에는 PERSONAL_SCORE_FLOOR를
    적용한다.

    개인 Wiki도 컷오프가 필요하다 — 검색은 매칭이 없어도 문서를 채워 반환하므로,
    거르지 않으면 무관한 주제에서 Wiki 목차 파일(Schema) 청크가 근거로 들어온다
    (2026-08-05 실측: '요가 스트레칭'·'커피 원두 로스팅'이 각각 0.000점 5건을
    돌려줬고, 5건 모두 같은 목차 문서의 청크였다).

    Args:
        connection: 검색에 사용할 DB 연결
        user_id: 검색 Scope 사용자 식별자
        query: 검색어
        topic_intent: 토픽 성격("news"|"evergreen"). 풀 신선도 하한을 정한다.

    Returns:
        개인 Wiki 문서와 컷오프를 통과한 풀 문서 목록
    """
    query_embeddings = await to_thread(embed_wiki_queries, [query])
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        hybrid = await prag_003(
            connection,
            user_id=user_id,
            query=query,
            query_embedding=query_embeddings.get(query.strip()),
        )
        freshness = await load_global_document_freshness(
            connection,
            [
                document.document_version_id
                for document in hybrid
                if document.namespace_key == GLOBAL_NAMESPACE
            ],
        )
    personal = select_personal_documents(hybrid)
    pool = select_pool_documents(
        hybrid, published_at=freshness, topic_intent=topic_intent
    )
    return [*personal, *pool]


async def search_global_documents(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    query: str,
    topic_intent: str = "news",
) -> list[ReportContextDocument]:
    """개인 Wiki를 건드리지 않고 Global 저장 자료만 검색한다."""
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        found = await load_global_report_context(connection, query=query)
        freshness = await load_global_document_freshness(
            connection,
            [document.document_version_id for document in found],
        )
    return select_pool_documents(
        found, published_at=freshness, topic_intent=topic_intent
    )


def describe_wiki_candidates(
    candidates: Sequence[WikiNavigationCandidate],
) -> str:
    """Reader가 30개 후보를 직접 고를 수 있는 짧은 Logical Index를 만든다."""
    if not candidates:
        return "Wiki 후보 없음."
    lines = [f"Wiki 후보 {len(candidates)}개. 읽을 후보의 document_version_id를 고른다."]
    for index, candidate in enumerate(candidates, start=1):
        summary = " ".join(candidate.summary.split())[:100]
        signals = []
        if candidate.exact_match:
            signals.append("exact")
        if candidate.alias_match:
            signals.append("alias")
        if candidate.keyword_rank is not None:
            signals.append(f"keyword={candidate.keyword_rank}")
        if candidate.vector_rank is not None:
            signals.append(f"vector={candidate.vector_rank}")
        signal_text = ",".join(signals) or "index"
        lines.append(
            f"{index}. [{candidate.document_version_id}] {candidate.title} "
            f"({signal_text}) — {summary}"
        )
    return "\n".join(lines)


def _packet_page_content(
    packet: WikiNavigationPacket, *, page_index: int
) -> str:
    """Page 발췌·관계·Source 시각을 생성기가 읽을 Context 문자열로 만든다."""
    page = packet.pages[page_index]
    sections = [page.summary.strip()]
    if page.excerpts:
        sections.append(
            "## Wiki 발췌\n"
            + "\n\n".join(excerpt.content.strip() for excerpt in page.excerpts)
        )
    elif page.markdown.strip():
        sections.append(page.markdown.strip())
    page_relations = [
        relation
        for relation in packet.relations
        if page.document_id
        in {relation.source_document_id, relation.target_document_id}
    ]
    if page_relations:
        relation_lines = []
        for relation in page_relations:
            supports = "; ".join(
                support.evidence.strip()
                for support in relation.supports
                if support.evidence.strip()
            )
            relation_lines.append(
                f"- {relation.source_document_id} -[{relation.relation_type}]-> "
                f"{relation.target_document_id}; rationale={relation.rationale}; "
                f"evidence={supports or '없음'}"
            )
        sections.append("## Wiki 관계\n" + "\n".join(relation_lines))
    page_sources = [
        source
        for source in packet.sources
        if source.wiki_document_version_id == page.document_version_id
    ]
    if page_sources:
        source_lines = [
            "- "
            f"saved_at={source.saved_at.isoformat()} "
            f"(기준={source.saved_at_source}), "
            f"stored_at={source.stored_at.isoformat()}, "
            f"published_at={source.published_at.isoformat() if source.published_at else '없음'}, "
            f"title={source.title}, url={source.url or '없음'}"
            for source in page_sources
        ]
        sections.append("## 사용자 저장 Source\n" + "\n".join(source_lines))
    return "\n\n".join(section for section in sections if section)


def navigation_packet_documents(
    packet: WikiNavigationPacket, *, user_id: str
) -> list[ReportContextDocument]:
    """Navigator Packet을 기존 Report Context 문서 경계로 변환한다."""
    candidate_scores = {
        candidate.document_version_id: candidate.rrf_score
        for candidate in packet.candidates
    }
    documents: list[ReportContextDocument] = []
    for index, page in enumerate(packet.pages, start=1):
        page_sources = [
            source
            for source in packet.sources
            if source.wiki_document_version_id == page.document_version_id
        ]
        score = candidate_scores.get(page.document_version_id)
        documents.append(
            ReportContextDocument(
                reference=f"P{index}",
                document_version_id=page.document_version_id,
                chunk_id=page.excerpts[0].chunk_id if page.excerpts else "",
                namespace_key=f"user/{user_id}",
                title=page.title,
                content=_packet_page_content(packet, page_index=index - 1),
                url=next(
                    (source.url for source in page_sources if source.url), None
                ),
                image_url=next(
                    (
                        source.image_url
                        for source in page_sources
                        if source.image_url
                    ),
                    None,
                ),
                score=(
                    max(float(score or 0.0), 1.0)
                    if page.role == "seed"
                    else max(float(score or 0.0), 0.8)
                ),
                context_role=(
                    "wiki_navigator_seed"
                    if page.role == "seed"
                    else "wiki_navigator_traversed"
                ),
                source_updated_at=page.updated_at.isoformat(),
            )
        )
    return documents


def _snapshot_datetime(value: object) -> datetime:
    """Job Snapshot의 ISO 문자열을 timezone 정보가 보존된 datetime으로 읽는다."""
    return datetime.fromisoformat(str(value))


def _snapshot_relations(
    raw_relations: object,
) -> tuple[WikiNavigationRelation, ...]:
    """Job Payload의 관계 Snapshot을 Navigator 관계 모델로 복원한다."""
    relations: list[WikiNavigationRelation] = []
    for raw in raw_relations or ():
        if not isinstance(raw, Mapping):
            continue
        supports = tuple(
            WikiNavigationRelationSupport(
                source_document_version_id=str(
                    support.get("source_document_version_id") or ""
                ),
                provenance_kind=str(support.get("provenance_kind") or ""),
                confidence=float(support.get("confidence") or 0.0),
                review_status=str(support.get("review_status") or ""),
                evidence=str(support.get("evidence") or ""),
                rationale=str(support.get("rationale") or ""),
            )
            for support in (raw.get("supports") or ())
            if isinstance(support, Mapping)
        )
        relations.append(
            WikiNavigationRelation(
                relation_id=str(raw.get("relation_id") or ""),
                source_document_id=str(raw.get("source_document_id") or ""),
                target_document_id=str(raw.get("target_document_id") or ""),
                relation_type=str(raw.get("relation_type") or ""),
                confidence=float(raw.get("confidence") or 0.0),
                provenance_kind=str(raw.get("provenance_kind") or ""),
                review_status=str(raw.get("review_status") or ""),
                rationale=str(raw.get("rationale") or ""),
                traversal_direction=str(raw.get("traversal_direction") or ""),
                hops=int(raw.get("hops") or 0),
                supports=supports,
            )
        )
    return tuple(relations)


def _snapshot_sources(raw_sources: object) -> tuple[WikiNavigationSource, ...]:
    """Job Payload의 Source 시간 Snapshot을 Navigator Source 모델로 복원한다."""
    sources: list[WikiNavigationSource] = []
    for raw in raw_sources or ():
        if not isinstance(raw, Mapping):
            continue
        published_at = raw.get("published_at")
        clipped_on = raw.get("clipped_on")
        sources.append(
            WikiNavigationSource(
                wiki_document_version_id=str(
                    raw.get("wiki_document_version_id") or ""
                ),
                source_document_id=str(raw.get("source_document_id") or ""),
                source_document_version_id=str(
                    raw.get("source_document_version_id") or ""
                ),
                source_type=str(raw.get("source_type") or ""),
                title=str(raw.get("title") or ""),
                url=str(raw["url"]) if raw.get("url") else None,
                relation_type=str(raw.get("relation_type") or ""),
                saved_at=_snapshot_datetime(raw.get("saved_at")),
                saved_at_source=str(raw.get("saved_at_source") or ""),
                stored_at=_snapshot_datetime(raw.get("stored_at")),
                published_at=(
                    _snapshot_datetime(published_at) if published_at else None
                ),
                clipped_on=date.fromisoformat(str(clipped_on)) if clipped_on else None,
            )
        )
    return tuple(sources)


async def load_navigation_snapshot_packet(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    topic: str,
    snapshot: Mapping[str, object],
) -> WikiNavigationPacket:
    """재시도 Job의 고정 Page Version·관계·Source Packet을 다시 구성한다."""
    raw_pages = snapshot.get("pages") or ()
    page_versions = [
        str(raw.get("document_version_id") or "").strip()
        for raw in raw_pages
        if isinstance(raw, Mapping)
        and str(raw.get("document_version_id") or "").strip()
    ]
    roles = {
        str(raw.get("document_version_id") or ""): str(raw.get("role") or "seed")
        for raw in raw_pages
        if isinstance(raw, Mapping)
    }
    wiki_version_id = str(snapshot.get("wiki_version_id") or "").strip() or None
    pages = await wnav_002(
        connection,
        user_id=user_id,
        document_version_ids=page_versions,
        wiki_version_id=wiki_version_id,
        max_chunks_per_page=2,
    )
    restored_pages = [
        replace(page, role=roles.get(page.document_version_id, page.role))
        for page in pages
    ]
    return await wnav_005(
        query=str(snapshot.get("query") or topic),
        wiki_version_id=wiki_version_id,
        candidates=(),
        pages=restored_pages,
        relations=_snapshot_relations(snapshot.get("relations")),
        sources=_snapshot_sources(snapshot.get("sources")),
        truncated=bool(snapshot.get("truncated") or False),
    )


def describe_documents(documents: Sequence[ReportContextDocument]) -> str:
    """도구 실행 결과를 LLM이 판단할 수 있는 관찰 문자열로 만든다.

    제목만 주면 관련성을 판단할 수 없고, 본문 전체를 주면 대화가 폭발한다.
    제목과 앞부분 발췌만 준다.
    """
    if not documents:
        return "결과 없음."
    lines = [f"{len(documents)}건을 찾았다."]
    for index, document in enumerate(documents, start=1):
        snippet = " ".join(document.content.split())[:_OBSERVATION_SNIPPET_CHARS]
        lines.append(f"{index}. {document.title}\n   {snippet}")
    return "\n".join(lines)


def pool_documents_for_decision(
    documents: Sequence[ReportContextDocument],
) -> list[ReportContextDocument]:
    """실시간 수집 여부 판정에 쓸 풀 문서만 문서 단위로 추린다.

    두 가지를 바로잡는다.

    1. **개인 Wiki를 세지 않는다.** 판정이 묻는 것은 "인터넷에 새로 나가야 하는가"
       인데, 어제 저장한 Wiki 문서가 있다고 오늘 소식이 필요 없어지지는 않는다.
       기존 고정 경로(graph.load_context)도 풀 문서만 센다.
    2. **같은 문서의 청크를 1건으로 센다.** Wiki 검색은 청크 단위로 반환하므로
       문서 하나가 5건으로 부풀어 기준(3건)을 넘겨버린다.

    (2026-08-05 실측: '요가 스트레칭'이 목차 문서 1개의 청크 5건으로 "자료 충분"
    판정을 받아 실시간 수집을 건너뛰었다.)

    Args:
        documents: 조사원이 모은 개인·풀 혼합 문서

    Returns:
        문서 단위로 중복을 제거한 풀 문서 목록
    """
    selected: list[ReportContextDocument] = []
    seen: set[str] = set()
    for document in documents:
        if getattr(document, "namespace_key", "") != GLOBAL_NAMESPACE:
            continue
        # 문서 ID가 없으면 URL로, 그것도 없으면 참조 ID로 문서를 구분한다.
        key = (
            str(getattr(document, "document_version_id", "") or "")
            or str(getattr(document, "url", "") or "")
            or document.reference
        )
        if key in seen:
            continue
        seen.add(key)
        selected.append(document)
    return selected


class DocumentCollector:
    """도구가 찾아낸 문서를 모으고, 중복 제거와 참조 번호 재부여를 한다.

    **참조 번호를 다시 매기는 이유**: 검색은 호출마다 P1·P2…를 처음부터 새로
    붙인다. 조사원은 검색을 여러 번 하므로 그대로 두면 서로 다른 문서가 같은
    P4를 갖는다. 하류의 `select_generation_context`가 참조 ID로 중복을 걸러
    **뒤에 온 문서를 조용히 버리고**, 인용도 엉뚱한 문서를 가리키게 된다.
    (2026-07-30 실측: 7건을 모았는데 P4가 3건이라 2건이 사라졌다.)
    """

    def __init__(self) -> None:
        """수집 상태를 초기화한다."""
        self._documents: list[ReportContextDocument] = []
        self._seen: set[str] = set()
        self._counters: dict[str, int] = {}

    def _next_reference(self, reference: str) -> str:
        """접두 문자(P/G/L)를 유지한 채 이어지는 번호를 부여한다."""
        match = re.match(r"[A-Za-z]+", reference or "")
        prefix = match.group(0) if match else "P"
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}{self._counters[prefix]}"

    def add(
        self, documents: Sequence[ReportContextDocument]
    ) -> list[ReportContextDocument]:
        """새 문서만 참조 번호를 다시 매겨 보관하고, 추가된 것을 반환한다."""
        added: list[ReportContextDocument] = []
        for document in documents:
            key = _document_key(document)
            if key in self._seen:
                continue
            self._seen.add(key)
            renumbered = replace(
                document, reference=self._next_reference(document.reference)
            )
            self._documents.append(renumbered)
            added.append(renumbered)
        return added

    @property
    def documents(self) -> tuple[ReportContextDocument, ...]:
        """지금까지 모인 문서를 반환한다."""
        return tuple(self._documents)


def merge_context_documents(
    *groups: Sequence[ReportContextDocument],
) -> list[ReportContextDocument]:
    """여러 검색 결과의 중복을 없애고 충돌하지 않는 참조 번호로 합친다."""
    collector = DocumentCollector()
    for documents in groups:
        collector.add(documents)
    return list(collector.documents)


def _timed_tool(tool: ToolSpec, stats: dict[str, list[int]]) -> ToolSpec:
    """도구 실행을 감싸 호출 횟수와 누적 소요 시간을 기록한다.

    `stats[이름] = [호출 수, 누적 ms]` 로 쌓는다. 실패한 호출도 시간을 쓰므로
    예외가 나도 기록한 뒤 다시 올린다.
    """
    run = tool.run

    async def _run(*args: object, **kwargs: object) -> str:
        started = monotonic()
        try:
            return await run(*args, **kwargs)
        finally:
            entry = stats.setdefault(tool.name, [0, 0])
            entry[0] += 1
            entry[1] += int((monotonic() - started) * 1000)

    return replace(tool, run=_run)


def build_research_tools(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    topic_intent: str,
    collector: DocumentCollector,
    navigation_session: WikiNavigationSession | None = None,
    wiki_version_id: str | None = None,
    allow_wiki_navigation: bool = True,
) -> list[ToolSpec]:
    """조사원이 사용할 도구 목록을 만든다.

    개인 Wiki의 Locate·Read와 Global 저장 검색을 나누어 준다. 실시간 수집은
    도구로 노출하지 않는다 — 언제 부를지가 "Global 근거가 몇 건인가"에 달린
    셈의 문제라 조사원이 끝난 뒤 `research_context`가 직접 판정한다.

    Args:
        connection: Report Graph가 보유하고 Navigator에도 그대로 전달할 DB 연결
        user_id: 검색 Scope에 사용할 사용자 식별자
        topic_intent: 토픽 성격("news"|"evergreen"). 풀 신선도 하한을 정한다.
        collector: 도구가 찾은 문서를 모을 수집기
        navigation_session: Locate 후보와 실제 읽은 Packet을 보존할 세션
        wiki_version_id: 읽기를 고정할 Wiki Build UUID
        allow_wiki_navigation: 재시도 Snapshot이 없을 때만 Wiki 도구를 노출할지

    Returns:
        LLM에 노출할 ToolSpec 목록
    """

    session = navigation_session or WikiNavigationSession()

    async def search_pool(query: str) -> str:
        """Global 저장 자료에서만 검색어로 근거를 찾는다."""
        if not query.strip():
            return "검색어가 비어 있다."
        found = await search_global_documents(
            connection, user_id=user_id, query=query, topic_intent=topic_intent
        )
        return describe_documents(collector.add(found))

    async def wiki_search(query: str) -> str:
        """개인 Wiki Logical Index에서 최대 30개 Page 후보를 찾는다."""
        normalized = query.strip()
        if not normalized:
            return "검색어가 비어 있다."
        query_embedding: Sequence[float] | None = None
        try:
            embeddings = await to_thread(embed_wiki_queries, [normalized])
            query_embedding = embeddings.get(normalized)
        except Exception as error:  # noqa: BLE001 - Keyword 후보 폴백
            logger.warning("Reader Wiki 임베딩 실패, Keyword로 폴백합니다: %s", error)
        candidates = await wnav_001(
            connection,
            user_id=user_id,
            query=normalized,
            wiki_version_id=wiki_version_id,
            limit=30,
            query_embedding=query_embedding,
        )
        session.remember_candidates(candidates, query=normalized)
        return describe_wiki_candidates(candidates)

    async def wiki_read(document_version_ids: list[str]) -> str:
        """Reader가 후보에서 선택한 Version을 읽고 관계·Source까지 수집한다."""
        if session.packets:
            return "이 Reader 실행에서는 Wiki Page를 이미 읽었다. 기존 Context를 쓴다."
        selected = list(
            dict.fromkeys(
                str(version_id).strip()
                for version_id in document_version_ids
                if str(version_id).strip()
            )
        )
        if not selected:
            return "읽을 document_version_id가 비어 있다."
        if len(selected) > 6:
            return "한 번에 읽을 Wiki Page는 최대 6개다."
        already_selected = {
            page.document_version_id
            for packet in session.packets
            for page in packet.pages
            if page.role == "seed"
        }
        if len(already_selected | set(selected)) > 6:
            return "한 Reader 실행에서 선택할 Wiki Seed Page는 최대 6개다."
        unknown = [
            version_id for version_id in selected if version_id not in session.candidates
        ]
        if unknown:
            return (
                "wiki_search 후보에 없는 document_version_id다: "
                + ", ".join(unknown)
            )
        packet = await wnav_006(
            connection,
            user_id=user_id,
            query=session.query or "Reader가 선택한 Wiki Page",
            selected_document_version_ids=selected,
            candidates=tuple(session.candidates.values()),
            wiki_version_id=wiki_version_id,
            max_depth=1,
            max_pages=6,
            max_chunks=12,
        )
        session.remember_packet(packet)
        added = collector.add(
            navigation_packet_documents(packet, user_id=user_id)
        )
        relation_count = len(packet.relations)
        source_count = len(packet.sources)
        return (
            describe_documents(added)
            + f"\n검증 관계 {relation_count}건, 저장 Source {source_count}건을 함께 읽었다."
        )

    wiki_tools = [
        ToolSpec(
            name="wiki_search",
            description=(
                "개인 Wiki의 Logical Index에서 질문과 관련된 Page 후보를 최대 "
                "30개 찾는다. 후보 목록은 내용 전체가 아니므로 이후 wiki_read가 필요하다."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "개인 Wiki에서 찾을 질문 또는 주제",
                    }
                },
                "required": ["query"],
            },
            run=wiki_search,
        ),
        ToolSpec(
            name="wiki_read",
            description=(
                "wiki_search 후보 중 질문에 필요한 Page Version을 선택해 본문·검증 "
                "관계·원본 저장 시각을 읽는다. 최대 6개 ID를 전달한다."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "document_version_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 6,
                        "description": "wiki_search가 반환한 document_version_id 목록",
                    }
                },
                "required": ["document_version_ids"],
            },
            run=wiki_read,
        ),
    ]
    return [
        *(wiki_tools if allow_wiki_navigation else []),
        ToolSpec(
            name="search_pool",
            description=(
                "미리 수집해 둔 Global 뉴스·외부 자료에서 최신 사실을 찾는다. "
                "개인 Wiki는 이 도구가 아니라 wiki_search와 wiki_read로 읽는다."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "찾을 검색어. 주제어 또는 연관 키워드",
                    }
                },
                "required": ["query"],
            },
            run=search_pool,
        ),
    ]


async def research_context(
    connection: AsyncConnection[DictRow],
    *,
    topic: str,
    user_id: str,
    topic_intent: str = "news",
    model: str = "gpt-4.1-mini",
    max_iterations: int = RESEARCH_MAX_ITERATIONS,
    planned_queries: Sequence[str] = (),
    planned_wiki_version_ids: Sequence[str] = (),
    wiki_version_id: str | None = None,
    job_id: str | None = None,
    navigation_snapshot: Mapping[str, object] | None = None,
) -> ResearchOutcome:
    """조사원이 저장된 자료를 훑고, 부족하면 실시간 수집으로 보강한다.

    **역할을 둘로 나눈다.** "무엇을 검색할까"는 LLM이 정하고(연관 키워드 확장),
    "몇 건이면 충분한가"는 `is_pool_sufficient`가 센다. 셈까지 LLM에게 맡겼을
    때 판단 정확도가 80%에 머물렀고, 프롬프트를 두 번 고쳐도 과호출이
    과소호출로 바뀔 뿐이었다(2026-07-31 벤치마크).

    개인 Wiki는 Reader가 `wiki_search → wiki_read`로 선택하고, Global 저장 자료는
    `search_pool`로 읽는다. 판정 대상은 `pool_documents_for_decision`이 추린
    Global 문서뿐이며 Navigator Page는 최종 근거에는 남되 수집 생략 개수에는
    포함하지 않는다.

    Args:
        connection: 검색에 사용할 DB 연결
        topic: 리포트 주제
        user_id: 대상 사용자 식별자
        topic_intent: 토픽 성격("news"|"evergreen")
        model: 조사 판단과 수집에 사용할 모델
        max_iterations: 도구 호출 왕복 상한
        planned_queries: 호출자가 확정한 연결 키워드. LLM 판단 전에 결정적으로
            Global 저장 검색하고, 실시간 보강에도 같은 목록을 사용한다.
        planned_wiki_version_ids: 관심사 Bundle이 고정한 Wiki Seed Version 목록
        wiki_version_id: 읽기를 고정할 Wiki Build UUID
        job_id: 첫 Reader Packet을 재시도 Payload에 저장할 Report Job UUID
        navigation_snapshot: 같은 Job의 첫 실행에서 고정한 Topic별 Packet Metadata

    Returns:
        모인 근거 문서와 도구 호출 기록
    """
    collector = DocumentCollector()
    navigation_session = WikiNavigationSession()
    normalized_planned: list[str] = []
    seen_queries = {topic.strip().casefold()}
    for raw_query in planned_queries:
        query = str(raw_query).strip()
        marker = query.casefold()
        if not query or marker in seen_queries:
            continue
        seen_queries.add(marker)
        normalized_planned.append(query)
    if normalized_planned:
        for query in (topic, *normalized_planned):
            found = await search_global_documents(
                connection,
                user_id=user_id,
                query=query,
                topic_intent=topic_intent,
            )
            collector.add(found)
    selected_planned_versions = list(
        dict.fromkeys(
            str(version_id).strip()
            for version_id in planned_wiki_version_ids
            if str(version_id).strip()
        )
    )[:6]
    if navigation_snapshot:
        packet = await load_navigation_snapshot_packet(
            connection,
            user_id=user_id,
            topic=topic,
            snapshot=navigation_snapshot,
        )
        navigation_session.remember_packet(packet)
        collector.add(navigation_packet_documents(packet, user_id=user_id))
    elif selected_planned_versions:
        packet = await wnav_006(
            connection,
            user_id=user_id,
            query=topic,
            selected_document_version_ids=selected_planned_versions,
            wiki_version_id=wiki_version_id,
            max_depth=1,
            max_pages=6,
            max_chunks=12,
        )
        navigation_session.remember_packet(packet)
        collector.add(navigation_packet_documents(packet, user_id=user_id))
    wiki_selection_fixed = bool(navigation_snapshot or selected_planned_versions)
    tools = build_research_tools(
        connection,
        user_id=user_id,
        topic_intent=topic_intent,
        collector=collector,
        navigation_session=navigation_session,
        wiki_version_id=wiki_version_id,
        allow_wiki_navigation=not wiki_selection_fixed,
    )
    # 도구별 호출 횟수와 소요 시간을 잰다. 3주제 리포트 336초 중 320초가 이
    # 노드였는데 안이 안 보여 어디를 줄일지 판단할 수 없었다(2026-08-11 실측,
    # 이송우 협의). 도구 실행만 감싸고 루프 로직은 건드리지 않는다.
    tool_stats: dict[str, list[int]] = {}
    tools = [_timed_tool(tool, tool_stats) for tool in tools]
    planned_note = (
        "\n아래 검색어는 요청에서 확정되어 이미 저장 자료 검색을 마쳤다: "
        + ", ".join([topic, *normalized_planned])
        + "\n선계획 검색 결과:\n"
        + describe_documents(collector.documents)
        + "\n같은 검색을 반복하지 말고, 이 결과에서 꼭 필요한 추가 방향만 찾는다."
        if normalized_planned
        else ""
    )
    result = await run_tool_loop(
        FIXED_WIKI_SYSTEM_PROMPT if wiki_selection_fixed else SYSTEM_PROMPT,
        f"리포트 주제: {topic}\n이 주제로 리포트를 쓸 근거 자료를 모아라.{planned_note}",
        tools,
        model=model,
        max_iterations=max_iterations,
    )
    if job_id and navigation_session.packets and not navigation_snapshot:
        await persist_report_navigation_snapshot(
            connection,
            user_id=user_id,
            job_id=job_id,
            topic=topic,
            packets=navigation_session.packets,
        )
    searched = len(collector.documents)
    decision_pool = pool_documents_for_decision(collector.documents)

    # 개수와 관련성을 모두 요구한다. 개수만 세면 무관한 기사 6건이 "충분"으로
    # 통과해 수집을 건너뛴다(2026-08-05 실측: '프로야구' 판정풀=6, 야구 기사 0건
    # → 반도체 리포트 발행).
    relevant = await to_thread(is_pool_relevant, topic, decision_pool)

    # 저장된 자료가 기준에 못 미치면 인터넷에서 보강한다. 실패해도 예외를
    # 올리지 않는다 — 수집이 안 됐다고 지금까지 모은 근거까지 버릴 이유는 없다.
    collected_live = False
    if not (is_pool_sufficient(decision_pool) and relevant):
        collected_live = True
        try:
            live_kwargs: dict[str, object] = {"model": model}
            if normalized_planned:
                live_kwargs["related_keywords"] = normalized_planned
            live = await to_thread(
                collect_live_context,
                topic,
                user_id,
                **live_kwargs,
            )
            collector.add(live)
        except Exception:
            logger.exception("실시간 수집에 실패해 저장된 자료만 사용합니다.")

    logger.info(
        "조사 완료: topic=%s 도구호출=%d 저장자료=%d 판정풀=%d 주제관련=%s 실시간수집=%s 최종=%d 종료=%s",
        topic,
        len(result.calls),
        searched,
        len(decision_pool),
        "예" if relevant else "아니오",
        "수행" if collected_live else "생략",
        len(collector.documents),
        result.stop_reason,
    )
    return ResearchOutcome(
        documents=collector.documents,
        calls=result.calls,
        notes=result.text,
        stop_reason=result.stop_reason,
        collected_live=collected_live,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        wiki_packets=tuple(navigation_session.packets),
        tool_stats=tuple(
            (name, calls, elapsed) for name, (calls, elapsed) in sorted(tool_stats.items())
        ),
    )
