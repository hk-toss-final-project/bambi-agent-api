"""LangGraph 기반 에이전트 그래프의 빌더와 실행 진입점.

Personal Wiki Build와 Report Builder Generation 오케스트레이션을 StateGraph로
정의한다. 개발 API(AgentWorkflowService)와 운영 Worker가 같은 그래프를
invoke하므로 실행 경로가 갈라지지 않는다. DB 노드는 각자 짧은
Transaction을 소유하고, LLM 노드는 Transaction 밖(스레드)에서 실행한다.
"""

from __future__ import annotations

import logging
from asyncio import to_thread
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from langgraph.graph import END, StateGraph
from psycopg import AsyncConnection

from agent.report_builder.api import (
    report_004,
    report_005,
    report_006,
    report_008,
    report_009,
    report_010,
    report_011,
    report_012,
    report_018,
    report_020,
    report_021,
    generate_report_content_with_quality,
    collect_live_context,
    related_keyword_fetch_limit,
    GLOBAL_NAMESPACE,
    critic_enabled,
    is_pool_relevant,
    is_pool_sufficient,
    research_agent_enabled,
    research_context,
    review_report,
    select_personal_documents,
    select_pool_documents,
    select_generation_context,
)
from agent.state import ReportGenerationState, PersonalWikiBuildState
from agent.wiki_builder.api import (
    classify_source_for_wiki,
    classify_wiki_source,
    wba_003,
)
from domain.interests.api import int_011
from domain.personal_wiki.documents.api import pwiki_002
from domain.personal_wiki.retrieval.api import prag_003, prag_006, prag_007
from infrastructure.persistence.api import (
    ConnectionInterestProfileRepository,
    get_user_source_document_version_for_agent,
    list_existing_wiki_entries,
    list_existing_wiki_relations,
    list_related_wiki_keywords,
    load_global_document_freshness,
    set_personal_wiki_scope,
    sync_wiki_interest_collection_targets,
)
from agent.assistant.api import resolve_topic_intent
from shared.contracts import FeatureRequest

logger = logging.getLogger("agent.graph")

type DictRow = dict[str, Any]

# 검토자 지적으로 다시 쓰는 횟수 상한. 검토자가 계속 흠을 잡으면 리포트 하나에
# LLM 호출이 무한히 늘어난다.
REVIEW_MAX_REVISIONS = 1


def build_personal_wiki_graph(connection: AsyncConnection[DictRow]) -> Any:
    """Personal Wiki Build 노드와 엣지를 조립해 컴파일된 그래프를 반환한다.

    load_source → classify → plan → persist → finalize 순서로 원본
    조회부터 문서·Chunk 저장, Job 결과 조립까지를 한 실행 경계로 묶는다.
    Embedding 생성은 2026-07-20 결정으로 실행 경로에서 제외했으며(활용처인
    Vector 검색 미도입), 재도입 시 persist 뒤에 embed 노드를 추가한다.
    """

    async def load_source(state: PersonalWikiBuildState) -> dict[str, Any]:
        """원본 Version과 기존 Wiki 상태를 한 조회 Transaction으로 읽는다."""
        user_id = state["user_id"]
        source_version_id = state["source_document_version_id"]
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=user_id)
            source = await get_user_source_document_version_for_agent(
                connection,
                user_id=user_id,
                source_document_version_id=source_version_id,
            )
            if source is None:
                raise ValueError(
                    f"개인 Wiki 원본 Version을 찾을 수 없습니다: {source_version_id}"
                )
            if not source.raw_content:
                raise ValueError(
                    f"DB에 Markdown 원문이 없습니다: {source_version_id}"
                )
            existing_entities = await list_existing_wiki_entries(
                connection, user_id=user_id, document_kind="entity"
            )
            existing_concepts = await list_existing_wiki_entries(
                connection, user_id=user_id, document_kind="concept"
            )
            existing_relations = await list_existing_wiki_relations(
                connection, namespace_key=source.namespace_key
            )
        return {
            "source": source,
            "existing_entities": existing_entities,
            "existing_concepts": existing_concepts,
            "existing_relations": existing_relations,
        }

    async def classify(state: PersonalWikiBuildState) -> dict[str, Any]:
        """Transaction 밖에서 원본 유형에 맞는 Wiki 분류를 실행한다."""
        source = state["source"]
        classification, classification_model = await to_thread(
            classify_wiki_source,
            source_type=source.source_type,
            source_metadata=source.source_metadata,
            source_title=source.title,
            source_content=source.raw_content,
            source_description=source.description,
            source_tags=source.tags,
            existing_entities=state["existing_entities"],
            existing_concepts=state["existing_concepts"],
            model=state["model"],
            classifier=classify_source_for_wiki,
        )
        return {
            "classification": classification,
            "classification_model": classification_model,
        }

    async def plan(state: PersonalWikiBuildState) -> dict[str, Any]:
        """분류 결과와 기존 Wiki 상태로 Build 계획을 만든다."""
        source = state["source"]
        build_plan = await wba_003(
            source_title=source.title,
            source_url=source.canonical_url,
            source_tags=source.tags,
            source_content_hash=source.content_hash,
            source_size_bytes=len(source.raw_content.encode("utf-8")),
            classification=state["classification"],
            existing_entities=state["existing_entities"],
            existing_concepts=state["existing_concepts"],
            generated_at=datetime.now(UTC).isoformat(),
            model=state.get("classification_model", state["model"]),
            existing_relations=state["existing_relations"],
        )
        return {"plan": build_plan}

    async def persist(state: PersonalWikiBuildState) -> dict[str, Any]:
        """계획된 문서·관계·Chunk·Build Snapshot을 저장 Transaction으로 기록한다."""
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=state["user_id"])
            persisted = await pwiki_002(
                connection,
                source=state["source"],
                plan=state["plan"],
                job_id=state["job_id"],
            )
        return {"persisted": persisted}

    async def finalize(state: PersonalWikiBuildState) -> dict[str, Any]:
        """Job 결과 계약에 맞는 최종 Payload를 조립한다."""
        source = state["source"]
        persisted = state["persisted"]
        build_plan = state["plan"]
        return {
            "result": {
                "source_document_id": source.source_document_id,
                "source_document_version_id": source.source_document_version_id,
                "wiki_version_id": persisted.wiki_version_id,
                "wiki_version": persisted.wiki_version,
                "chunk_count": persisted.chunk_count,
                "extracted_relation_count": build_plan.extracted_relation_count,
                "stored_relation_count": persisted.stored_relation_count,
                "isolated_node_count": build_plan.isolated_node_count,
                "relation_warnings": build_plan.relation_warnings,
                "affected_documents": [
                    {
                        "document_id": document.document_id,
                        "document_version_id": document.document_version_id,
                        "document_kind": document.document_kind,
                        "document_key": document.document_key,
                        "file_path": document.file_path,
                        "version": document.version,
                        "action": document.action,
                    }
                    for document in persisted.affected_documents
                ],
                "artifacts": {
                    "index": build_plan.index.content,
                    "source": build_plan.source_manifest.content,
                    "log": build_plan.log_entry.content,
                },
            }
        }

    graph = StateGraph(PersonalWikiBuildState)
    graph.add_node("load_source", load_source)
    graph.add_node("classify", classify)
    graph.add_node("plan", plan)
    graph.add_node("persist", persist)
    graph.add_node("finalize", finalize)
    graph.set_entry_point("load_source")
    graph.add_edge("load_source", "classify")
    graph.add_edge("classify", "plan")
    graph.add_edge("plan", "persist")
    graph.add_edge("persist", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


async def _recalculate_interest_profile(
    connection: AsyncConnection[DictRow], *, user_id: str
) -> None:
    """Build 완료 직후 관심사 프로필을 재계산한다(INT-011 자동 훅).

    프로필은 Wiki의 파생물이므로, 재계산 실패가 이미 저장된 Build 성공을
    실패로 뒤집으면 안 된다. 실패는 경고 로그로만 남긴다(다음 Build 또는
    수동 rebuild API가 복구 경로다).
    """
    try:
        repository = ConnectionInterestProfileRepository(connection)
        profile = await int_011(repository, user_id)
        logger.info(
            "관심사 프로필 자동 재계산 완료 (user=%s, version=%s)",
            user_id,
            profile.get("version"),
        )
        # 상위 관심사를 창고 수집 대상에 얹는다. 관심사는 Wiki 노드 제목에서
        # 나오는데 창고는 온보딩 taxonomy 라벨로만 채워져서, 이게 없으면 사용자가
        # 실제로 파고든 주제일수록 리포트가 근거를 못 찾는다.
        subscribed = await sync_wiki_interest_collection_targets(
            connection, user_id=user_id, interests=profile.get("interests") or []
        )
        if subscribed:
            logger.info(
                "관심사 수집 대상 등록 (user=%s): %s", user_id, ", ".join(subscribed)
            )
    except Exception:  # noqa: BLE001 — 파생물 갱신 실패는 Build 결과에 영향 없음
        logger.warning(
            "관심사 프로필 자동 재계산 실패 — Wiki Build 결과는 유지 (user=%s)",
            user_id,
            exc_info=True,
        )


async def run_personal_wiki_build(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_document_version_id: str,
    job_id: str,
    model: str = "gpt-4.1-mini",
) -> dict[str, object]:
    """Personal Wiki Build 그래프를 실행하고 Job 결과 Payload를 반환한다.

    개발 API와 Worker가 공유하는 유일한 Wiki Build 실행 진입점이다.
    Build 성공 후에는 관심사 프로필을 자동 재계산해(INT-011) 프로필이
    항상 최신 Wiki를 따라가게 한다 — Wiki가 원천, 프로필은 파생물.
    """
    graph = build_personal_wiki_graph(connection)
    state = await graph.ainvoke(
        {
            "user_id": user_id,
            "source_document_version_id": source_document_version_id,
            "job_id": job_id,
            "model": model,
        }
    )
    await _recalculate_interest_profile(connection, user_id=user_id)
    return dict(state["result"])


# 한 주제에 최소한 이만큼은 근거를 남긴다. 주제 수로 균등 분배만 하면 주제가
# 늘수록 각 섹션이 근거 1~2건으로 얇아져 요약이 아니라 헤드라인 나열이 된다.
_MIN_TOPIC_CONTEXT_DOCUMENTS = 3

# 생성 프롬프트에 넣는 근거 문서 상한(REPORT-006 기본값과 같아야 한다).
_MAX_REPORT_CONTEXTS = 12


def _report_topics(state: ReportGenerationState) -> list[str]:
    """이 리포트가 다룰 주제 목록을 돌려준다.

    topics가 비어 있으면 기존처럼 topic 하나만 다룬다. topics가 있으면 topic은
    카드 제목·generation_topic 용도로만 남고 본문이 다루는 주제는 이 목록이다.
    """
    topics = [str(topic).strip() for topic in (state.get("topics") or [])]
    return [topic for topic in topics if topic] or [state["topic"]]


def build_report_generation_graph(connection: AsyncConnection[DictRow]) -> Any:
    """리포트 생성기 콘텐츠 생성 노드와 엣지를 조립해 컴파일된 그래프를 반환한다.

    load_context → generate → persist 순서로 검색·생성·영속화를 잇는다.
    """

    async def research(state: ReportGenerationState) -> dict[str, Any]:
        """조사원 에이전트가 도구를 골라 가며 근거 자료를 모은다.

        LLM이 search_pool·collect_live 중 무엇을 어떤 검색어로 부를지 스스로
        정한다. 실패하거나 한 건도 못 모으면 빈 목록을 돌려주고, load_context가
        기존 고정 경로로 되돌아간다 — 조사가 안 됐다고 생성까지 막지는 않는다.

        주제가 여럿이면(아침 요약처럼 상위 관심사를 묶는 경우) 주제마다 조사를
        따로 돌린다. 한 번에 합쳐 검색하면 서로 무관한 주제가 섞여 어느 쪽도
        제대로 못 찾는다(2026-08-05 실측: 무관한 주제는 제목 임베딩 유사도가
        0.40을 넘지 못해 풀 판정 자체가 갈린다).
        """
        topics = _report_topics(state)
        intents: dict[str, str] = {}
        documents_by_topic: dict[str, list[Any]] = {}
        notes: list[str] = []
        calls: list[dict[str, object]] = []
        collected_live = False
        for topic in topics:
            intents[topic] = await to_thread(
                resolve_topic_intent, topic, state["user_id"]
            )
            documents_by_topic[topic] = []
            if not research_agent_enabled():
                continue
            try:
                outcome = await research_context(
                    connection,
                    topic=topic,
                    user_id=state["user_id"],
                    topic_intent=intents[topic],
                    model=state["model"],
                )
            except Exception:
                # 주제 하나가 실패해도 나머지 주제는 계속 조사한다. 실패한 주제는
                # load_context가 고정 경로로 다시 시도한다.
                logger.exception(
                    "조사원 실행에 실패해 기존 수집 경로로 되돌립니다: topic=%s", topic
                )
                continue
            documents_by_topic[topic] = list(outcome.documents)
            collected_live = collected_live or outcome.collected_live
            if outcome.notes:
                notes.append(
                    outcome.notes if len(topics) == 1 else f"[{topic}] {outcome.notes}"
                )
            calls.extend(
                {
                    "topic": topic,
                    "tool": call.name,
                    "arguments": call.arguments,
                    "failed": call.failed,
                }
                for call in outcome.calls
            )
        flattened = [
            document
            for topic in topics
            for document in documents_by_topic.get(topic, [])
        ]
        return {
            # 기존 단일 주제 필드는 대표 주제 값으로 유지한다 — load_context의
            # 고정 경로와 로그가 그대로 읽는다.
            "topic_intent": intents.get(state["topic"], next(iter(intents.values()))),
            "topic_intents": intents,
            "research_documents": flattened,
            "research_documents_by_topic": documents_by_topic,
            "research_notes": "\n".join(notes),
            "research_collected_live": collected_live,
            "research_calls": calls,
        }

    async def load_related_keywords(user_id: str, topic: str) -> list[str]:
        """개인 Wiki 그래프에서 토픽과 1홉으로 연결된 이웃 키워드를 읽는다.

        관심 키워드 하나로만 수집하면 '코스피' 리포트에 코스닥시장 기사가 걸리지
        않는데, 그 연결은 Wiki Builder가 이미 저장해 둔 것이다.

        조회 실패는 리포트 생성을 막지 않는다 — 확장은 수집을 넓히는 보조 수단
        이므로, 실패하면 원 키워드 하나로 진행한다. 개인 Wiki 검색과 Transaction을
        분리한 것도 같은 이유다(여기서 실패해도 검색 결과를 되돌리지 않는다).

        Args:
            user_id: 조회 대상 사용자 ID
            topic: 리포트 주제로 들어온 관심 키워드

        Returns:
            연결 강도 내림차순 이웃 키워드 제목. 확장이 꺼져 있거나 실패하면 빈 목록.
        """
        limit = related_keyword_fetch_limit()
        if limit <= 0:
            return []
        try:
            async with connection.transaction():
                await set_personal_wiki_scope(connection, user_id=user_id)
                related = await list_related_wiki_keywords(
                    connection, user_id=user_id, topic=topic, limit=limit
                )
        except Exception as error:
            logger.warning(
                "Wiki 이웃 키워드 조회 실패, 원 키워드로 진행한다 (topic=%s): %s",
                topic,
                error,
            )
            return []
        logger.info(
            "Wiki 이웃 키워드 %d건 (topic=%s, 이웃=%s)",
            len(related),
            topic,
            [item.title for item in related],
        )
        return [item.title for item in related]

    async def load_context(state: ReportGenerationState) -> dict[str, Any]:
        """조사원이 모은 자료를 생성용 Context로 다듬는다.

        조사원이 자료를 모았으면 그대로 쓰고, 비었으면 기존 고정 경로(개인 Wiki
        조회 → 풀 판정 → 부족하면 실시간 수집)를 그대로 수행한다.
        """
        topics = _report_topics(state)
        if len(topics) > 1:
            return await _load_multi_topic_contexts(state, topics)
        researched = list(state.get("research_documents") or [])
        if researched:
            logger.info(
                "조사원 자료 사용: topic=%s %d건 (도구 호출 %d회)",
                state["topic"],
                len(researched),
                len(state.get("research_calls") or []),
            )
            return await _finalize_contexts(state, researched)
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=state["user_id"])
            hybrid = await prag_003(
                connection,
                user_id=state["user_id"],
                query=state["topic"],
            )
            # 풀 문서의 신선도는 같은 조회 Transaction에서 함께 읽는다 — Scope가
            # 이미 설정돼 있고, 왕복을 늘리지 않는다.
            # 참조 ID가 없는 형태(테스트 더미 등)도 그대로 통과시킨다
            # (select_generation_context와 같은 관용 규칙).
            pool_freshness = await load_global_document_freshness(
                connection,
                [
                    str(getattr(document, "document_version_id", "") or "")
                    for document in hybrid
                ],
            )
        # prag_003은 개인 Wiki와 Global 풀을 함께 검색한다. 풀에 **확실히 쓸 만한**
        # 자료가 있으면 실시간 수집을 생략한다. 목적은 속도가 아니라 셋이다.
        #
        #   1. Job 이중 실행 방지 — 실행이 Worker lease(600초)에 근접하면 시스템이
        #      죽은 것으로 보고 같은 Job을 다시 돌린다(리포트 중복·LLM 비용 2배).
        #   2. 외부 API 한도 — 사용자마다 뉴스·YouTube·Reddit을 직접 호출하면
        #      금방 차단된다(2026-07-28 실측: GDELT 429). 풀은 한 번 모아 여럿이 쓴다.
        #   3. 출처 증빙 — 풀 문서는 캐시 문서 ID(gsrc:)가 있는 G 참조가 된다. 실시간 자료는
        #      URL이 유일한 증빙이라 원문이 바뀌면 근거를 확인할 수 없다.
        #
        # 판정이 헐거우면 오히려 손해다. 잡음 수준 문서로 수집을 건너뛰면 리포트가
        # 얕아진다(같은 날 실측: 'Anthropic'이 잡음 5건으로 통과해 사실과 다른 서술
        # 생성). select_pool_documents가 절대 하한으로 그 경우를 걸러낸다.
        # 토픽 성격은 research 노드가 이미 판정했다. 다시 부르지 않는다.
        topic_intent = str(state.get("topic_intent") or "news")
        pool_documents = select_pool_documents(
            hybrid, published_at=pool_freshness, topic_intent=topic_intent
        )
        # 개수와 관련성을 모두 요구한다(조사원 경로와 같은 규칙).
        pool_is_relevant = await to_thread(
            is_pool_relevant, state["topic"], pool_documents
        )
        pool_is_enough = is_pool_sufficient(pool_documents) and pool_is_relevant
        logger.info(
            "풀 근거 판정: topic=%s intent=%s 풀 채택 %d건 주제관련=%s → 실시간 수집 %s",
            state["topic"],
            topic_intent,
            len(pool_documents),
            "예" if pool_is_relevant else "아니오",
            "생략" if pool_is_enough else "수행",
        )

        # 탈락시킨 풀 문서는 근거에서도 뺀다. 판정에만 쓰고 근거로는 그대로 넘기면
        # 잡음이 뒷문으로 다시 들어가고(실측: 무관한 "Microsoft 사이버보안" 기사가
        # 인용됨), 근거 상한(12건)을 먼저 차지해 실시간 수집분이 밀려난다.
        # 조사원 경로와 같은 점수 하한을 쓴다. 여기에만 하한이 없어서, 조사원이
        # 빈손으로 돌아와 이 경로로 넘어오는 순간 0점짜리 Wiki 목차 조각이 근거로
        # 들어왔다(2026-08-05 실측: '고대 이집트 미라 제작'이 'API 키 발급' 인용).
        personal_only = select_personal_documents(hybrid)
        contextualized = await prag_006([*personal_only, *pool_documents])
        personal = await report_004(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph",
                user_id=state["user_id"],
                payload={"implementation": lambda: contextualized},
            )
        )
        personal_documents = personal.data.get("result", [])

        # REPORT-005: 실시간 외부 자료(뉴스 RSS·YouTube·Reddit)를 키워드 비서로 수집한다.
        # 이전에는 개인 Wiki 결과를 그대로 흘려보내는 패스스루라, 저장된 문서만 근거가 됐다.
        # 네트워크·LLM이 걸리는 동기 함수라 Transaction 밖 스레드에서 실행한다.
        # 조사원이 이미 실시간 수집을 시도했으면 다시 부르지 않는다. 조사원이
        # 빈손으로 돌아오면 이 경로로 넘어오는데, 같은 주제로 같은 수집을 한 번
        # 더 돌리면 지연과 외부 API 호출이 두 배가 된다. 실패했다면 조건이
        # 같으므로 대개 또 실패한다.
        already_collected_live = bool(state.get("research_collected_live"))
        skip_live = pool_is_enough or already_collected_live
        # 수집을 실제로 돌 때만 이웃을 조회한다 — 건너뛸 거면 DB 왕복이 낭비다.
        related_keywords = (
            [] if skip_live else await load_related_keywords(state["user_id"], state["topic"])
        )
        if already_collected_live and not pool_is_enough:
            logger.info(
                "실시간 수집 생략: topic=%s 조사원이 이미 시도했다.", state["topic"]
            )
        live = await report_005(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph",
                user_id=state["user_id"],
                payload={
                    "implementation": (
                        (lambda: [])
                        if skip_live
                        else lambda: to_thread(
                            collect_live_context,
                            state["topic"],
                            state["user_id"],
                            model=state["model"],
                            related_keywords=related_keywords,
                        )
                    )
                },
            )
        )
        # REPORT-006: 개인 Wiki 맥락과 실시간 근거를 합쳐 생성에 넣을 자료를 고른다.
        selected = await report_006(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph",
                user_id=state["user_id"],
                payload={
                    "implementation": lambda: select_generation_context(
                        personal_documents,
                        live.data.get("result", []),
                    )
                },
            )
        )
        personalized = await report_012(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph",
                user_id=state["user_id"],
                payload={"implementation": lambda: selected.data.get("result", [])},
            )
        )
        contexts = personalized.data.get("result")
        if not isinstance(contexts, list):
            raise RuntimeError("REPORT 검색 기능이 Context 목록을 반환하지 않았습니다.")
        return {"contexts": contexts}

    async def _topic_documents(state: ReportGenerationState, topic: str) -> list[Any]:
        """주제 하나가 쓸 근거 문서를 모은다(여러 주제를 묶는 경로 전용).

        조사원이 그 주제로 모은 자료를 우선 쓰고, 빈손이면 저장된 자료만 다시
        검색한다. 여기서는 실시간 수집을 하지 않는다 — 주제 수만큼 외부 수집을
        돌리면 Worker lease(600초)를 넘겨 같은 Job이 죽은 것으로 판정되고, 조사원
        단계에서 이미 수집 기회가 한 번 있었기 때문이다.
        """
        researched = list(
            (state.get("research_documents_by_topic") or {}).get(topic) or []
        )
        if researched:
            return researched
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=state["user_id"])
            hybrid = await prag_003(
                connection, user_id=state["user_id"], query=topic
            )
            pool_freshness = await load_global_document_freshness(
                connection,
                [
                    str(getattr(document, "document_version_id", "") or "")
                    for document in hybrid
                ],
            )
        intents = state.get("topic_intents") or {}
        topic_intent = str(intents.get(topic) or "news")
        # 단일 주제 경로와 같은 하한을 쓴다. 여기에만 하한이 없으면 0점짜리
        # Wiki 목차 조각이 근거로 들어온다.
        pool_documents = select_pool_documents(
            hybrid, published_at=pool_freshness, topic_intent=topic_intent
        )
        return [*select_personal_documents(hybrid), *pool_documents]

    async def _load_multi_topic_contexts(
        state: ReportGenerationState, topics: list[str]
    ) -> dict[str, Any]:
        """주제마다 근거 몫을 따로 배정해 한 리포트용 Context로 합친다.

        근거 상한(12건)을 주제 수로 나눠 배분한다. 그냥 이어 붙이면 앞 주제가
        상한을 다 먹어 뒤 주제는 근거 0건이 되고, 그 섹션은 근거 없이 쓰이거나
        빠진다.
        """
        quota = max(_MIN_TOPIC_CONTEXT_DOCUMENTS, _MAX_REPORT_CONTEXTS // len(topics))
        merged: list[Any] = []
        seen: set[str] = set()
        for topic in topics:
            documents = await _topic_documents(state, topic)
            finalized = await _finalize_contexts(state, documents, max_documents=quota)
            picked = 0
            for context in finalized.get("contexts", []):
                key = str(getattr(context, "reference", None) or context)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(context)
                picked += 1
            logger.info(
                "주제별 근거 배정: topic=%s 몫=%d건 확보=%d건", topic, quota, picked
            )
        if not merged:
            raise RuntimeError("여러 주제 리포트에 쓸 근거를 한 건도 모으지 못했습니다.")
        return {"contexts": merged}

    async def _finalize_contexts(
        state: ReportGenerationState,
        documents: list[Any],
        *,
        max_documents: int = _MAX_REPORT_CONTEXTS,
    ) -> dict[str, Any]:
        """조사원이 모은 문서를 생성용 Context로 다듬는다.

        고정 경로와 같은 REPORT-004/006/012 단계를 그대로 거친다 — 자료를 누가
        모았든 근거 상한·개인화 규칙은 동일해야 하기 때문이다. REPORT-005(실시간
        수집)는 조사원이 이미 도구로 수행했으므로 건너뛴다.
        """
        contextualized = await prag_006(documents)
        personal = await report_004(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph",
                user_id=state["user_id"],
                payload={"implementation": lambda: contextualized},
            )
        )
        selected = await report_006(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph",
                user_id=state["user_id"],
                payload={
                    "implementation": lambda: select_generation_context(
                        personal.data.get("result", []),
                        [],
                        max_documents=max_documents,
                    )
                },
            )
        )
        personalized = await report_012(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph",
                user_id=state["user_id"],
                payload={"implementation": lambda: selected.data.get("result", [])},
            )
        )
        contexts = personalized.data.get("result")
        if not isinstance(contexts, list):
            raise RuntimeError("REPORT 검색 기능이 Context 목록을 반환하지 않았습니다.")
        return {"contexts": contexts}

    async def generate(state: ReportGenerationState) -> dict[str, Any]:
        """Transaction 밖에서 LLM 생성을 실행하고 지연 시간을 기록한다."""
        started = monotonic()
        summary = await report_008(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph",
                user_id=state["user_id"],
                payload={
                    # 생성 후 무료 품질 검사를 거쳐, 근거 미인용·너무 짧음 등이면
                    # 교정 지시를 붙여 한 번 재생성한다(품질 루프). load_context의
                    # 위키 검색 흐름은 건드리지 않고 생성 단계 안에서만 동작한다.
                    "implementation": lambda: to_thread(
                        generate_report_content_with_quality,
                        topic=state["topic"],
                        topics=_report_topics(state),
                        content_type=state["content_type"],
                        language=state["language"],
                        contexts=state["contexts"],
                        model=state["model"],
                        # 검토자가 지적해 다시 들어온 경우 그 지시를 반영해 쓴다.
                        correction=str(state.get("review_correction") or ""),
                    )
                },
            )
        )
        body = await report_009(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph",
                user_id=state["user_id"],
                payload={"implementation": lambda: summary.data.get("result")},
            )
        )
        tagged = await report_010(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph",
                user_id=state["user_id"],
                # 태그는 본문과 같은 생성 응답에서 함께 받는다(parse_report_generation이
                # normalize_content_tags로 정리한다). 별도 LLM 호출을 두지 않는 것이
                # 이 설계의 요점이다 — 추가 비용·지연 없이 제목·본문과 같은 근거를
                # 바탕으로 태그가 나온다(2026-08-05 이송우 협의).
                payload={"implementation": lambda: body.data.get("result")},
            )
        )
        cited = await report_011(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph",
                user_id=state["user_id"],
                payload={"implementation": lambda: tagged.data.get("result")},
            )
        )
        generated = cited.data.get("result")
        if generated is None:
            raise RuntimeError("REPORT 생성 기능이 콘텐츠를 반환하지 않았습니다.")
        return {
            "generated": generated,
            "review_correction": "",
            "latency_ms": int((monotonic() - started) * 1000),
        }

    async def review(state: ReportGenerationState) -> dict[str, Any]:
        """검토자 에이전트가 초안의 인용을 근거 원문과 대조한다.

        `quality.py`의 무료 코드 검사는 이미 generate 안에서 끝났다. 여기는
        글자 수로는 알 수 없는 사실관계를 본다 — 검토자가 도구로 원문을 직접
        꺼내 확인한다.

        검토가 불가능하면(스위치 꺼짐·LLM 장애·응답 파손) 그대로 통과시킨다.
        검토는 품질을 높이는 장치지 발행을 막는 관문이 아니다.
        """
        attempts = int(state.get("review_attempts") or 0)
        if not critic_enabled():
            return {"review_outcome": "disabled", "review_correction": ""}
        verdict = await review_report(
            connection,
            content=state["generated"],
            contexts=state["contexts"],
            user_id=state["user_id"],
            topic=state["topic"],
            topic_intent=str(state.get("topic_intent") or "news"),
            model=state["model"],
        )
        if not verdict.should_regenerate:
            return {
                "review_outcome": verdict.outcome,
                "review_correction": "",
                "review_problem": "",
            }
        # 재작성은 한 번만 허용한다. 검토자가 계속 흠을 잡으면 비용이 무한히 는다.
        if attempts >= REVIEW_MAX_REVISIONS:
            logger.info(
                "검토 재작성 상한(%d회) 도달, 지적을 남기고 발행합니다: %s",
                REVIEW_MAX_REVISIONS,
                verdict.problem,
            )
            # 지적 내용을 함께 남긴다. 결과 코드만으로는 "왜 못 고쳤는지"를 알 수
            # 없어 로그를 뒤져야 했다(2026-08-05 실측: 같은 진단에 반나절이 들었다).
            return {
                "review_outcome": "revise_exhausted",
                "review_correction": "",
                "review_problem": verdict.problem,
            }
        logger.info("검토자가 재작성을 요구했습니다: %s", verdict.problem)
        return {
            "review_outcome": verdict.outcome,
            "review_correction": verdict.correction,
            "review_problem": verdict.problem,
            "review_attempts": attempts + 1,
        }

    def route_after_review(state: ReportGenerationState) -> str:
        """검토 결과에 따라 재작성으로 돌아갈지 저장으로 갈지 정한다."""
        return "generate" if state.get("review_correction") else "persist"

    async def persist(state: ReportGenerationState) -> dict[str, Any]:
        """생성 Run·후보·Citation·Snapshot·Outbox를 저장 Transaction으로 기록한다."""
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=state["user_id"])
            citations = await prag_007(
                connection,
                job_id=state["job_id"],
                user_id=state["user_id"],
                attempt_number=state["attempt_number"],
                content_type=state["content_type"],
                generated=state["generated"],
                contexts=state["contexts"],
                latency_ms=state["latency_ms"],
                review_outcome=str(state.get("review_outcome") or ""),
                review_problem=str(state.get("review_problem") or ""),
            )
            persisted = await report_018(
                FeatureRequest(
                    request_id=state["job_id"],
                    actor_id="report-generation-graph",
                    user_id=state["user_id"],
                    payload={"implementation": lambda: dict(citations)},
                )
            )
        completed = await report_020(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph",
                user_id=state["user_id"],
                payload={"implementation": lambda: dict(persisted.data)},
            )
        )
        safeguarded = await report_021(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph",
                user_id=state["user_id"],
                payload={"implementation": lambda: dict(completed.data)},
            )
        )
        return {"result": dict(safeguarded.data)}

    graph = StateGraph(ReportGenerationState)
    graph.add_node("research", research)
    graph.add_node("load_context", load_context)
    graph.add_node("generate", generate)
    graph.add_node("review", review)
    graph.add_node("persist", persist)
    graph.set_entry_point("research")
    graph.add_edge("research", "load_context")
    graph.add_edge("load_context", "generate")
    graph.add_edge("generate", "review")
    # 검토자가 사실관계 문제를 찾으면 generate로 돌려보낸다(최대 1회).
    graph.add_conditional_edges(
        "review", route_after_review, {"generate": "generate", "persist": "persist"}
    )
    graph.add_edge("persist", END)
    return graph.compile()


async def run_report_generation(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
    attempt_number: int,
    topic: str,
    topics: list[str] | None = None,
    content_type: str,
    language: str,
    model: str = "gpt-4.1-mini",
) -> dict[str, object]:
    """Report Builder Generation 그래프를 실행하고 저장 결과 Payload를 반환한다.

    개발 API와 Worker가 공유하는 유일한 생성 실행 진입점이다.
    """
    graph = build_report_generation_graph(connection)
    state = await graph.ainvoke(
        {
            "user_id": user_id,
            "job_id": job_id,
            "attempt_number": attempt_number,
            "topic": topic,
            "topics": list(topics or []),
            "content_type": content_type,
            "language": language,
            "model": model,
        }
    )
    return dict(state["result"])
