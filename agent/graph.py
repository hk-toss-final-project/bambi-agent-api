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
    report_011,
    report_012,
    report_018,
    report_020,
    report_021,
    generate_report_content_with_quality,
    collect_live_context,
    GLOBAL_NAMESPACE,
    is_pool_sufficient,
    select_pool_documents,
    select_generation_context,
)
from agent.state import ReportGenerationState, PersonalWikiBuildState
from agent.wiki_builder.api import classify_source_for_wiki, wba_003
from domain.interests.api import int_011
from domain.personal_wiki.documents.api import pwiki_002
from domain.personal_wiki.retrieval.api import prag_003, prag_006, prag_007
from infrastructure.persistence.api import (
    ConnectionInterestProfileRepository,
    get_user_source_document_version_for_agent,
    list_existing_wiki_entries,
    list_existing_wiki_relations,
    load_global_document_freshness,
    set_personal_wiki_scope,
)
from agent.assistant.api import resolve_topic_intent
from shared.contracts import FeatureRequest

logger = logging.getLogger("agent.graph")

type DictRow = dict[str, Any]


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
        """Transaction 밖에서 LLM 분류를 실행한다."""
        source = state["source"]
        classification = await to_thread(
            classify_source_for_wiki,
            source_title=source.title,
            source_content=source.raw_content,
            source_description=source.description,
            source_tags=source.tags,
            existing_entities=state["existing_entities"],
            existing_concepts=state["existing_concepts"],
            model=state["model"],
        )
        return {"classification": classification}

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
            model=state["model"],
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


def build_report_generation_graph(connection: AsyncConnection[DictRow]) -> Any:
    """리포트 생성기 콘텐츠 생성 노드와 엣지를 조립해 컴파일된 그래프를 반환한다.

    load_context → generate → persist 순서로 검색·생성·영속화를 잇는다.
    """

    async def load_context(state: ReportGenerationState) -> dict[str, Any]:
        """개인 Wiki와 Global 최신 문서 Context를 조회 Transaction으로 읽는다."""
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
        topic_intent = await to_thread(
            resolve_topic_intent, state["topic"], state["user_id"]
        )
        pool_documents = select_pool_documents(
            hybrid, published_at=pool_freshness, topic_intent=topic_intent
        )
        pool_is_enough = is_pool_sufficient(pool_documents)
        logger.info(
            "풀 근거 판정: topic=%s intent=%s 풀 채택 %d건 → 실시간 수집 %s",
            state["topic"],
            topic_intent,
            len(pool_documents),
            "생략" if pool_is_enough else "수행",
        )

        # 탈락시킨 풀 문서는 근거에서도 뺀다. 판정에만 쓰고 근거로는 그대로 넘기면
        # 잡음이 뒷문으로 다시 들어가고(실측: 무관한 "Microsoft 사이버보안" 기사가
        # 인용됨), 근거 상한(12건)을 먼저 차지해 실시간 수집분이 밀려난다.
        personal_only = [
            document
            for document in hybrid
            if getattr(document, "namespace_key", "") != GLOBAL_NAMESPACE
        ]
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
        live = await report_005(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph",
                user_id=state["user_id"],
                payload={
                    "implementation": (
                        (lambda: [])
                        if pool_is_enough
                        else lambda: to_thread(
                            collect_live_context,
                            state["topic"],
                            state["user_id"],
                            model=state["model"],
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
                        content_type=state["content_type"],
                        language=state["language"],
                        contexts=state["contexts"],
                        model=state["model"],
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
        cited = await report_011(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="report-generation-graph",
                user_id=state["user_id"],
                payload={"implementation": lambda: body.data.get("result")},
            )
        )
        generated = cited.data.get("result")
        if generated is None:
            raise RuntimeError("REPORT 생성 기능이 콘텐츠를 반환하지 않았습니다.")
        return {
            "generated": generated,
            "latency_ms": int((monotonic() - started) * 1000),
        }

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
    graph.add_node("load_context", load_context)
    graph.add_node("generate", generate)
    graph.add_node("persist", persist)
    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "generate")
    graph.add_edge("generate", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


async def run_report_generation(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
    attempt_number: int,
    topic: str,
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
            "content_type": content_type,
            "language": language,
            "model": model,
        }
    )
    return dict(state["result"])
