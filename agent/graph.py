"""LangGraph 기반 에이전트 그래프의 빌더와 실행 진입점.

Personal Wiki Build와 Bambi Generation 오케스트레이션을 StateGraph로
정의한다. 개발 API(AgentWorkflowService)와 운영 Worker가 같은 그래프를
invoke하므로 실행 경로가 갈라지지 않는다. DB 노드는 각자 짧은
Transaction을 소유하고, LLM 노드는 Transaction 밖(스레드)에서 실행한다.
"""

from __future__ import annotations

from asyncio import to_thread
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from langgraph.graph import END, StateGraph
from psycopg import AsyncConnection

from agent.bambi.api import (
    bambi_004,
    bambi_005,
    bambi_008,
    bambi_009,
    bambi_011,
    bambi_012,
    bambi_018,
    bambi_020,
    bambi_021,
    generate_bambi_content,
)
from agent.state import BambiGenerationState, PersonalWikiBuildState
from agent.wiki_builder.api import classify_source_for_wiki, wba_003
from domain.personal_wiki.documents.api import pwiki_002
from domain.personal_wiki.retrieval.api import prag_003, prag_006, prag_007
from infrastructure.persistence.api import (
    get_user_source_document_version_for_agent,
    list_existing_wiki_entries,
    list_existing_wiki_relations,
    set_personal_wiki_scope,
)
from shared.contracts import FeatureRequest

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
    return dict(state["result"])


def build_bambi_generation_graph(connection: AsyncConnection[DictRow]) -> Any:
    """밤비 콘텐츠 생성 노드와 엣지를 조립해 컴파일된 그래프를 반환한다.

    load_context → generate → persist 순서로 검색·생성·영속화를 잇는다.
    """

    async def load_context(state: BambiGenerationState) -> dict[str, Any]:
        """개인 Wiki와 Global 최신 문서 Context를 조회 Transaction으로 읽는다."""
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=state["user_id"])
            hybrid = await prag_003(
                connection,
                user_id=state["user_id"],
                query=state["topic"],
            )
        contextualized = await prag_006(hybrid)
        personal = await bambi_004(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="bambi-generation-graph",
                user_id=state["user_id"],
                payload={
                    "implementation": lambda: contextualized
                },
            )
        )
        combined = await bambi_005(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="bambi-generation-graph",
                user_id=state["user_id"],
                payload={"implementation": lambda: personal.data.get("result", [])},
            )
        )
        personalized = await bambi_012(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="bambi-generation-graph",
                user_id=state["user_id"],
                payload={"implementation": lambda: combined.data.get("result", [])},
            )
        )
        contexts = personalized.data.get("result")
        if not isinstance(contexts, list):
            raise RuntimeError("BAMBI 검색 기능이 Context 목록을 반환하지 않았습니다.")
        return {"contexts": contexts}

    async def generate(state: BambiGenerationState) -> dict[str, Any]:
        """Transaction 밖에서 LLM 생성을 실행하고 지연 시간을 기록한다."""
        started = monotonic()
        summary = await bambi_008(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="bambi-generation-graph",
                user_id=state["user_id"],
                payload={
                    "implementation": lambda: to_thread(
                        generate_bambi_content,
                        topic=state["topic"],
                        content_type=state["content_type"],
                        language=state["language"],
                        contexts=state["contexts"],
                        model=state["model"],
                    )
                },
            )
        )
        body = await bambi_009(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="bambi-generation-graph",
                user_id=state["user_id"],
                payload={"implementation": lambda: summary.data.get("result")},
            )
        )
        cited = await bambi_011(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="bambi-generation-graph",
                user_id=state["user_id"],
                payload={"implementation": lambda: body.data.get("result")},
            )
        )
        generated = cited.data.get("result")
        if generated is None:
            raise RuntimeError("BAMBI 생성 기능이 콘텐츠를 반환하지 않았습니다.")
        return {
            "generated": generated,
            "latency_ms": int((monotonic() - started) * 1000),
        }

    async def persist(state: BambiGenerationState) -> dict[str, Any]:
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
            persisted = await bambi_018(
                FeatureRequest(
                    request_id=state["job_id"],
                    actor_id="bambi-generation-graph",
                    user_id=state["user_id"],
                    payload={"implementation": lambda: dict(citations)},
                )
            )
        completed = await bambi_020(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="bambi-generation-graph",
                user_id=state["user_id"],
                payload={"implementation": lambda: dict(persisted.data)},
            )
        )
        safeguarded = await bambi_021(
            FeatureRequest(
                request_id=state["job_id"],
                actor_id="bambi-generation-graph",
                user_id=state["user_id"],
                payload={"implementation": lambda: dict(completed.data)},
            )
        )
        return {"result": dict(safeguarded.data)}

    graph = StateGraph(BambiGenerationState)
    graph.add_node("load_context", load_context)
    graph.add_node("generate", generate)
    graph.add_node("persist", persist)
    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "generate")
    graph.add_edge("generate", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


async def run_bambi_generation(
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
    """Bambi Generation 그래프를 실행하고 저장 결과 Payload를 반환한다.

    개발 API와 Worker가 공유하는 유일한 생성 실행 진입점이다.
    """
    graph = build_bambi_generation_graph(connection)
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


def build_quality_evaluation_graph() -> object:
    """콘텐츠 품질 평가와 재생성 분기 그래프를 생성한다."""
    raise NotImplementedError("품질 평가 그래프 구현이 필요합니다.")
