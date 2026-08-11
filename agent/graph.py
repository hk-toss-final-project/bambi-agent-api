"""LangGraph 기반 에이전트 그래프의 빌더와 실행 진입점.

Personal Wiki Build와 Report Builder Generation 오케스트레이션을 StateGraph로
정의한다. 개발 API(AgentWorkflowService)와 운영 Worker가 같은 그래프를
invoke하므로 실행 경로가 갈라지지 않는다. DB 노드는 각자 짧은
Transaction을 소유하고, LLM 노드는 Transaction 밖(스레드)에서 실행한다.
"""

from __future__ import annotations

import asyncio
import logging
from asyncio import to_thread
from dataclasses import dataclass, replace
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
    embed_wiki_queries,
    is_pool_relevant,
    is_pool_sufficient,
    merge_context_documents,
    navigation_packet_documents,
    LEGACY_READ_PIPELINE_VERSION,
    research_agent_enabled,
    research_context,
    research_context_for_version,
    review_report,
    select_personal_documents,
    select_pool_documents,
    focus_documents_on_topic,
    generate_topic_facets,
    select_generation_context,
    search_global_documents,
)
from agent.change_history.api import (
    change_history_available,
    chg_001,
    current_reference_date,
    merge_topic_delta_reports,
)
from agent.state import ReportGenerationState, PersonalWikiBuildState
from agent.wiki_builder.api import (
    WikiGraphExpansionEdge,
    WikiNodeIdentity,
    build_relation_candidate_sets,
    classify_source_for_wiki,
    classify_wiki_source,
    expand_wiki_graph,
    generate_relation_query_embeddings,
    link_wiki_relations,
    prepare_wiki_identity_resolution,
    rebuild_full_wiki,
    resolve_onboarding_contexts,
    resolve_wiki_identity_conflicts,
    validate_wiki_identity_quality,
    wba_003,
    wba_011,
    wba_014,
)
from domain.interests.api import int_011
from domain.personal_wiki.documents.api import pwiki_002
from domain.personal_wiki.navigation.api import wnav_006
from domain.personal_wiki.retrieval.api import prag_003, prag_006, prag_007
from infrastructure.persistence.api import (
    ConnectionInterestProfileRepository,
    WikiGraphRelationSnapshot,
    get_user_source_document_version_for_agent,
    list_existing_wiki_entries,
    list_existing_wiki_relations,
    list_cached_custom_topic_contexts,
    list_onboarding_topic_contexts,
    list_onboarding_wiki_anchor_keys,
    list_related_wiki_keywords,
    list_wiki_graph_relation_snapshot,
    list_wiki_node_embeddings,
    list_user_source_versions_for_rebuild,
    load_global_document_freshness,
    load_pinned_wiki_context,
    persist_report_navigation_snapshot,
    retire_personal_wiki_without_sources,
    set_personal_wiki_scope,
    save_custom_topic_contexts,
    sync_wiki_interest_collection_targets,
)
from agent.assistant.api import resolve_topic_intent
from shared.contracts import FeatureRequest
from shared.wiki_models import ExistingWikiEntry

logger = logging.getLogger("agent.graph")

type DictRow = dict[str, Any]

# 검토자 지적으로 다시 쓰는 횟수 상한. 검토자가 계속 흠을 잡으면 리포트 하나에
# LLM 호출이 무한히 늘어난다.
REVIEW_MAX_REVISIONS = 1


def build_personal_wiki_graph(
    connection: AsyncConnection[DictRow],
    *,
    embedding_batch_threshold: int = 0,
) -> Any:
    """Personal Wiki Build 노드와 엣지를 조립해 컴파일된 그래프를 반환한다.

    load_source → resolve_onboarding_context → classify → prepare_identity →
    (필요 시 resolve_identity) →
    quality_gate → recall_candidates → link_relations → plan → validate_plan →
    persist → embed → finalize 순서로 추출·관계 판정을 분리한다. Embedding은
    기존 노드 후보 recall에만 쓰고, Edge는 원문 근거와 신뢰도를 검증한
    Relation Linker만 확정한다.
    """

    async def load_source(state: PersonalWikiBuildState) -> dict[str, Any]:
        """원본 Version과 기존 Wiki 상태를 한 조회 Transaction으로 읽는다."""
        user_id = state["user_id"]
        source_version_id = state["source_document_version_id"]
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=user_id)
            source = state.get("source")
            if source is None:
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
            onboarding_anchor_keys = await list_onboarding_wiki_anchor_keys(
                connection, namespace_key=source.namespace_key
            )
            node_embeddings = await list_wiki_node_embeddings(
                connection,
                namespace_key=source.namespace_key,
                model_name="text-embedding-3-small",
            )
            taxonomy_contexts = []
            cached_custom_contexts = []
            if source.source_type == "onboarding_seed":
                taxonomy_version = str(
                    source.source_metadata.get("interest_taxonomy_version") or ""
                ).strip()
                raw_custom_labels = source.source_metadata.get("custom_labels", [])
                custom_labels = (
                    [str(item) for item in raw_custom_labels]
                    if isinstance(raw_custom_labels, list)
                    else []
                )
                preferred_language = str(
                    source.source_metadata.get("preferred_language") or "ko"
                )
                if taxonomy_version:
                    taxonomy_contexts = await list_onboarding_topic_contexts(
                        connection,
                        taxonomy_version=taxonomy_version,
                        locale="ko-KR",
                    )
                cached_custom_contexts = await list_cached_custom_topic_contexts(
                    connection,
                    user_id=user_id,
                    keywords=custom_labels,
                    locale=preferred_language,
                )
        return {
            "source": source,
            "existing_entities": existing_entities,
            "existing_concepts": existing_concepts,
            "existing_relations": existing_relations,
            "onboarding_anchor_keys": onboarding_anchor_keys,
            "node_embeddings": node_embeddings,
            "taxonomy_contexts": taxonomy_contexts,
            "cached_custom_contexts": cached_custom_contexts,
        }

    async def resolve_onboarding_context(
        state: PersonalWikiBuildState,
    ) -> dict[str, Any]:
        """정식 Topic은 DB에서, 사용자 키워드는 캐시·LLM·폴백으로 해석한다."""
        source = state["source"]
        if source.source_type != "onboarding_seed":
            return {
                "onboarding_contexts": [],
                "generated_custom_contexts": [],
                "onboarding_context_model": "not-applicable",
                "onboarding_context_warnings": [],
            }
        metadata = source.source_metadata
        raw_topic_ids = metadata.get("selected_topic_ids", [])
        raw_custom_labels = metadata.get("custom_labels", [])
        selected_topic_ids = (
            [str(item) for item in raw_topic_ids]
            if isinstance(raw_topic_ids, list)
            else []
        )
        custom_labels = (
            [str(item) for item in raw_custom_labels]
            if isinstance(raw_custom_labels, list)
            else []
        )
        taxonomy_version = str(
            metadata.get("interest_taxonomy_version") or ""
        ).strip() or None
        preferred_language = str(metadata.get("preferred_language") or "ko")
        resolution = await to_thread(
            resolve_onboarding_contexts,
            selected_topic_ids=selected_topic_ids,
            custom_keywords=custom_labels,
            taxonomy_version=taxonomy_version,
            locale=preferred_language,
            taxonomy_contexts=state.get("taxonomy_contexts", []),
            cached_contexts=state.get("cached_custom_contexts", []),
            existing_entries=[
                *state["existing_entities"],
                *state["existing_concepts"],
            ],
            model=state["model"],
        )
        return {
            "onboarding_contexts": list(resolution.contexts),
            "generated_custom_contexts": list(resolution.generated_contexts),
            "onboarding_context_model": resolution.model_trace,
            "onboarding_context_warnings": list(resolution.warnings),
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
            onboarding_contexts=state.get("onboarding_contexts", []),
        )
        return {
            "classification": classification,
            "classification_model": classification_model,
        }

    async def prepare_identity(state: PersonalWikiBuildState) -> dict[str, Any]:
        """표기 정규화로 확정 가능한 노드를 병합하고 의미 충돌만 추린다."""
        draft = prepare_wiki_identity_resolution(
            classification=state["classification"],
            existing_entities=state["existing_entities"],
            existing_concepts=state["existing_concepts"],
        )
        return {"resolution_draft": draft}

    def route_identity_resolution(state: PersonalWikiBuildState) -> str:
        """의미 충돌이 있을 때만 LLM identity 판정 노드로 보낸다."""
        return "resolve" if state["resolution_draft"].conflicts else "quality"

    async def resolve_identity(state: PersonalWikiBuildState) -> dict[str, Any]:
        """모호한 후보군 전체를 Transaction 밖의 한 LLM 호출로 판정한다."""
        result = await to_thread(
            resolve_wiki_identity_conflicts,
            draft=state["resolution_draft"],
            source_title=state["source"].title,
            model=state["model"],
        )
        return {"identity_resolution": result}

    async def quality_gate(state: PersonalWikiBuildState) -> dict[str, Any]:
        """canonical 중복과 잘못된 기존 key가 저장 단계로 넘어가지 않게 막는다."""
        resolution = state.get("identity_resolution")
        draft = state["resolution_draft"]
        classification = (
            resolution.classification if resolution is not None else draft.classification
        )
        validate_wiki_identity_quality(
            classification=classification,
            existing_entities=state["existing_entities"],
            existing_concepts=state["existing_concepts"],
        )
        return {
            "classification": classification,
            "identity_resolution_model": (
                resolution.model
                if resolution is not None
                else "deterministic:wiki-surface-v1"
            ),
            "identity_conflict_count": (
                resolution.resolved_conflict_count if resolution is not None else 0
            ),
            "identity_input_tokens": (
                resolution.input_tokens if resolution is not None else 0
            ),
            "identity_output_tokens": (
                resolution.output_tokens if resolution is not None else 0
            ),
        }

    async def recall_candidates(state: PersonalWikiBuildState) -> dict[str, Any]:
        """표면형·어휘·Vector·Graph·온보딩 신호로 관계 판정 후보를 모은다."""
        classification = state["classification"]
        source = state["source"]
        if source.source_type == "onboarding_seed":
            # 온보딩 시드 자체는 LLM 없이 결정적으로 저장한다. 후속
            # 클리핑이 들어올 때 이 노드가 anchor 후보로 제공된다.
            return {
                "relation_candidates": {},
                "relation_candidate_count": 0,
                "relation_recall_warnings": [],
            }
        query_texts = [
            f"{entity.name}\n{entity.description}".strip()
            for entity in classification.entities
        ] + [
            f"{concept.title}\n{concept.definition}".strip()
            for concept in classification.concepts
        ]
        candidate_embeddings = {
            WikiNodeIdentity(item.document_kind, item.document_key): item.embedding
            for item in state.get("node_embeddings", [])
        }
        query_embeddings: dict[str, tuple[float, ...]] = {}
        warnings: list[str] = []
        if query_texts and candidate_embeddings:
            try:
                vectors = await to_thread(
                    generate_relation_query_embeddings,
                    query_texts,
                    model="text-embedding-3-small",
                )
                query_embeddings = {
                    f"N{index}": vector
                    for index, vector in enumerate(vectors, start=1)
                }
            except Exception as error:  # noqa: BLE001 - lexical·anchor 폴백 유지
                logger.warning(
                    "Wiki 관계 Vector 후보 생성 실패, 비Vector 후보로 진행: %s",
                    error,
                )
                warnings.append(f"Vector 관계 후보 생성 실패: {error}")
        candidates = build_relation_candidate_sets(
            classification=classification,
            existing_entries=[
                *state["existing_entities"],
                *state["existing_concepts"],
            ],
            existing_relations=state["existing_relations"],
            onboarding_anchor_ids=[
                WikiNodeIdentity(kind, key)
                for kind, key in state.get("onboarding_anchor_keys", [])
            ],
            query_embeddings=query_embeddings,
            candidate_embeddings=candidate_embeddings,
        )
        return {
            "relation_candidates": candidates,
            "relation_candidate_count": sum(
                len(items) for items in candidates.values()
            ),
            "relation_recall_warnings": warnings,
        }

    async def link_relations(state: PersonalWikiBuildState) -> dict[str, Any]:
        """전체 후보를 항상 한 번 검토해 근거 있는 관계와 노드 처리를 확정한다."""
        source = state["source"]
        if source.source_type == "onboarding_seed":
            return {
                "relation_linker_model": "deterministic:onboarding-anchor-v1",
            }
        linked = await to_thread(
            link_wiki_relations,
            source_title=source.title,
            source_content=source.raw_content,
            classification=state["classification"],
            candidates_by_node=state["relation_candidates"],
            model=state["model"],
        )
        if state.get("relation_recall_warnings"):
            linked = replace(
                linked,
                relation_warnings=list(
                    dict.fromkeys(
                        [
                            *linked.relation_warnings,
                            *state["relation_recall_warnings"],
                        ]
                    )
                ),
            )
        return {
            "classification": linked,
            "relation_linker_model": state["model"],
        }

    async def plan(state: PersonalWikiBuildState) -> dict[str, Any]:
        """분류 결과와 기존 Wiki 상태로 Build 계획을 만든다."""
        source = state["source"]
        classification_trace = state.get("classification_model", state["model"])
        if state.get("onboarding_contexts"):
            classification_trace = (
                f"{classification_trace};context="
                f"{state.get('onboarding_context_model', 'unknown')}"
            )
        model_trace = (
            f"{classification_trace};"
            f"identity={state['identity_resolution_model']};"
            f"relation={state.get('relation_linker_model', state['model'])}"
        )
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
            model=model_trace,
            existing_relations=state["existing_relations"],
        )
        return {"plan": build_plan}

    async def validate_plan(state: PersonalWikiBuildState) -> dict[str, Any]:
        """저장 예정 Snapshot의 중복·고립·관계 근거·Hub 품질을 Lint한다."""
        entries = {
            (entry.document_kind, entry.document_key): entry
            for entry in [
                *state["existing_entities"],
                *state["existing_concepts"],
            ]
        }
        for document in [*state["plan"].entities, *state["plan"].concepts]:
            entries[(document.document_kind, document.document_key)] = ExistingWikiEntry(
                document_kind=document.document_kind,
                document_key=document.document_key,
                title=document.title,
                domain=document.domain,
                summary=document.summary,
                metadata=document.metadata,
            )
        report = await wba_014(list(entries.values()), state["plan"].relations)
        if not report.passed:
            errors = [
                issue.message for issue in report.issues if issue.severity == "error"
            ]
            raise ValueError("Wiki 품질 게이트 실패: " + "; ".join(errors[:5]))
        return {
            "quality_metrics": dict(report.metrics),
            "quality_warnings": [
                issue.message
                for issue in report.issues
                if issue.severity == "warning"
            ],
        }

    async def persist(state: PersonalWikiBuildState) -> dict[str, Any]:
        """계획된 문서·관계·Chunk·Build Snapshot을 저장 Transaction으로 기록한다."""
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=state["user_id"])
            custom_context_cache_count = await save_custom_topic_contexts(
                connection,
                user_id=state["user_id"],
                contexts=state.get("generated_custom_contexts", []),
            )
            persisted = await pwiki_002(
                connection,
                source=state["source"],
                plan=state["plan"],
                job_id=state["job_id"],
            )
        return {
            "persisted": persisted,
            "custom_context_cache_count": custom_context_cache_count,
        }

    async def embed(state: PersonalWikiBuildState) -> dict[str, Any]:
        """변경된 Entity·Concept Chunk를 Vector로 갱신해 다음 Build 후보 검색에 쓴다."""
        version_ids = [
            document.document_version_id
            for document in state["persisted"].affected_documents
            if document.document_kind in {"entity", "concept"}
            and document.action in {"create", "created", "update", "updated"}
        ]
        if not version_ids:
            return {"embedding_count": 0, "embedding_warning": None}
        try:
            count = await wba_011(
                connection,
                namespace_key=state["source"].namespace_key,
                document_version_ids=version_ids,
                model="text-embedding-3-small",
                job_id=state["job_id"],
                batch_threshold=embedding_batch_threshold,
            )
            return {"embedding_count": count, "embedding_warning": None}
        except Exception as error:  # noqa: BLE001 - Wiki 저장은 이미 완료됨
            logger.warning(
                "Wiki Embedding 갱신 실패, 다음 Build는 비Vector 후보로 진행: %s",
                error,
            )
            return {
                "embedding_count": 0,
                "embedding_warning": str(error),
            }

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
                "relation_candidate_count": state.get(
                    "relation_candidate_count", 0
                ),
                "node_dispositions": [
                    {
                        "node_name": item.node_name,
                        "node_kind": item.node_kind,
                        "disposition": item.disposition,
                        "reason": item.reason,
                        "matched_existing_key": item.matched_existing_key,
                    }
                    for item in build_plan.node_dispositions
                ],
                "quality": {
                    "metrics": state.get("quality_metrics", {}),
                    "warnings": state.get("quality_warnings", []),
                },
                "embedding_count": state.get("embedding_count", 0),
                "embedding_warning": state.get("embedding_warning"),
                "onboarding_context": {
                    "model": state.get("onboarding_context_model", "not-applicable"),
                    "resolved_count": len(state.get("onboarding_contexts", [])),
                    "cached_count": state.get("custom_context_cache_count", 0),
                    "warnings": state.get("onboarding_context_warnings", []),
                },
                "identity_resolution": {
                    "model": state["identity_resolution_model"],
                    "resolved_conflict_count": state["identity_conflict_count"],
                    "input_tokens": state["identity_input_tokens"],
                    "output_tokens": state["identity_output_tokens"],
                },
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
    graph.add_node("resolve_onboarding_context", resolve_onboarding_context)
    graph.add_node("classify", classify)
    graph.add_node("prepare_identity", prepare_identity)
    graph.add_node("resolve_identity", resolve_identity)
    graph.add_node("quality_gate", quality_gate)
    graph.add_node("recall_candidates", recall_candidates)
    graph.add_node("link_relations", link_relations)
    graph.add_node("plan", plan)
    graph.add_node("validate_plan", validate_plan)
    graph.add_node("persist", persist)
    graph.add_node("embed", embed)
    graph.add_node("finalize", finalize)
    graph.set_entry_point("load_source")
    graph.add_edge("load_source", "resolve_onboarding_context")
    graph.add_edge("resolve_onboarding_context", "classify")
    graph.add_edge("classify", "prepare_identity")
    graph.add_conditional_edges(
        "prepare_identity",
        route_identity_resolution,
        {"resolve": "resolve_identity", "quality": "quality_gate"},
    )
    graph.add_edge("resolve_identity", "quality_gate")
    graph.add_edge("quality_gate", "recall_candidates")
    graph.add_edge("recall_candidates", "link_relations")
    graph.add_edge("link_relations", "plan")
    graph.add_edge("plan", "validate_plan")
    graph.add_edge("validate_plan", "persist")
    graph.add_edge("persist", "embed")
    graph.add_edge("embed", "finalize")
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
    embedding_batch_threshold: int = 0,
) -> dict[str, object]:
    """Personal Wiki Build 그래프를 실행하고 Job 결과 Payload를 반환한다.

    개발 API와 Worker가 공유하는 유일한 Wiki Build 실행 진입점이다.
    Build 성공 후에는 관심사 프로필을 자동 재계산해(INT-011) 프로필이
    항상 최신 Wiki를 따라가게 한다 — Wiki가 원천, 프로필은 파생물.
    """
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        source = await get_user_source_document_version_for_agent(
            connection,
            user_id=user_id,
            source_document_version_id=source_document_version_id,
        )
    if source is None:
        raise ValueError(
            f"개인 Wiki 원본 Version을 찾을 수 없습니다: {source_document_version_id}"
        )
    if (
        source.source_type == "onboarding_seed"
        and (
            getattr(source, "head_current_version", None)
            or getattr(source, "version", 1)
        )
        > 1
    ):
        rebuilt = await rebuild_full_wiki(
            connection,
            user_id=user_id,
            job_id=job_id,
            model=model,
            embedding_batch_threshold=embedding_batch_threshold,
        )
        await _recalculate_interest_profile(connection, user_id=user_id)
        persisted = rebuilt.persisted
        return {
            "source_document_id": source.source_document_id,
            "source_document_version_id": source.source_document_version_id,
            "wiki_version_id": persisted.wiki_version_id,
            "wiki_version": persisted.wiki_version,
            "chunk_count": persisted.chunk_count,
            "stored_relation_count": persisted.stored_relation_count,
            "full_rebuild": True,
            "source_count": rebuilt.source_count,
            "superseded_document_count": rebuilt.superseded_document_count,
            "embedding_count": rebuilt.embedding_count,
            "quality": {
                "metrics": dict(rebuilt.quality.metrics),
                "warnings": [
                    issue.message
                    for issue in rebuilt.quality.issues
                    if issue.severity == "warning"
                ],
            },
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
        }

    graph = build_personal_wiki_graph(
        connection,
        embedding_batch_threshold=embedding_batch_threshold,
    )
    state = await graph.ainvoke(
        {
            "user_id": user_id,
            "source_document_version_id": source_document_version_id,
            "job_id": job_id,
            "model": model,
            "source": source,
        }
    )
    await _recalculate_interest_profile(connection, user_id=user_id)
    return dict(state["result"])


def _full_rebuild_payload(rebuilt: Any) -> dict[str, object]:
    """전체 Wiki 재구성 결과를 Job 결과 Payload로 변환한다."""
    persisted = rebuilt.persisted
    return {
        "wiki_version_id": persisted.wiki_version_id,
        "wiki_version": persisted.wiki_version,
        "chunk_count": persisted.chunk_count,
        "stored_relation_count": persisted.stored_relation_count,
        "full_rebuild": True,
        "source_count": rebuilt.source_count,
        "superseded_document_count": rebuilt.superseded_document_count,
        "embedding_count": rebuilt.embedding_count,
        "quality": {
            "metrics": dict(rebuilt.quality.metrics),
            "warnings": [
                issue.message
                for issue in rebuilt.quality.issues
                if issue.severity == "warning"
            ],
        },
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
    }


async def run_personal_wiki_rebuild(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
    model: str = "gpt-4.1-mini",
    embedding_batch_threshold: int = 0,
) -> dict[str, object]:
    """남은 활성 원본 전체로 Wiki를 재구성하고 빈 원본 상태도 안전하게 반영한다."""
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        sources = await list_user_source_versions_for_rebuild(
            connection, user_id=user_id
        )
    if not sources:
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=user_id)
            retired = await retire_personal_wiki_without_sources(
                connection, user_id=user_id, job_id=job_id
            )
        return {
            "full_rebuild": True,
            "source_count": 0,
            "affected_documents": [],
            "stored_relation_count": 0,
            "embedding_count": 0,
            **retired,
        }
    rebuilt = await rebuild_full_wiki(
        connection,
        user_id=user_id,
        job_id=job_id,
        model=model,
        embedding_batch_threshold=embedding_batch_threshold,
    )
    await _recalculate_interest_profile(connection, user_id=user_id)
    return _full_rebuild_payload(rebuilt)


# 한 주제에 최소한 이만큼은 근거를 남긴다. 주제 수로 균등 분배만 하면 주제가
# 늘수록 각 섹션이 근거 1~2건으로 얇아져 요약이 아니라 헤드라인 나열이 된다.
_MIN_TOPIC_CONTEXT_DOCUMENTS = 3

# 한 리포트에서 실시간 수집을 돌릴 수 있는 주제 수 상한.
#
# 아침·온디맨드가 주제 3개를 보내므로 3개까지는 전부 채울 수 있어야 한다. 실측
# 기준 수집 1회가 30~60초, 생성이 약 50초라 3개를 다 수집해도 3분 안팎이고 Worker
# lease(600초)의 절반 이하다. 상한을 없애지는 않는다 — 계약상 topics는 최대 5개까지
# 올 수 있고, 5개를 전부 수집하면 lease에 근접한다.
_MAX_LIVE_COLLECT_TOPICS = 3
# 주제당 더할 보조 검색어 수. 3개로 시작했다가 되돌렸다 — 검색어가 4배가 되자
# 조사원이 결과를 보고 다시 판단하는 왕복이 그만큼 늘어 리스 600초를 두 번
# 연속 넘겼다(2026-08-11 실측: 192초 → 1485·1713초). 검색 자체는 16~22초로
# 그대로였고 늘어난 것은 LLM 판단 시간이었다. 1개부터 다시 잰다.
_MAX_TOPIC_FACETS = 1

# 생성 프롬프트에 넣는 근거 문서 상한(REPORT-006 기본값과 같아야 한다).
_MAX_REPORT_CONTEXTS = 12

# 주제별 조사 및 수집 실행 시간 상한(초). 특정 외부 API 응답 지연이 전체 보고서
# 생성을 10분 이상 지연시켜 워커 타임아웃/재시도가 발생하는 것을 방지한다.
_TOPIC_RESEARCH_TIMEOUT_SECONDS = 90.0



@dataclass(frozen=True, slots=True)
class _WikiKeywordExpansion:
    """검색 수집에 전달할 Graph 확장 제목과 품질 Gate 결과."""

    keywords: tuple[str, ...]
    mode: str
    gate_passed: bool
    maturity_reasons: tuple[str, ...] = ()


def _expand_wiki_graph_keywords(
    topic: str,
    snapshot: list[WikiGraphRelationSnapshot],
    *,
    top_k: int,
) -> _WikiKeywordExpansion:
    """Persistence Snapshot을 Agent Edge로 바꿔 bounded PPR/1-hop을 계산한다."""
    if top_k <= 0:
        return _WikiKeywordExpansion((), "empty", False)

    node_details: dict[WikiNodeIdentity, tuple[str, str | None]] = {}
    relation_nodes: list[
        tuple[WikiGraphRelationSnapshot, WikiNodeIdentity, WikiNodeIdentity]
    ] = []
    for relation in snapshot:
        source = WikiNodeIdentity(
            relation.source_document_kind,
            relation.source_document_key,
        )
        target = WikiNodeIdentity(
            relation.target_document_kind,
            relation.target_document_key,
        )
        node_details[source] = (relation.source_title.strip(), relation.source_domain)
        node_details[target] = (relation.target_title.strip(), relation.target_domain)
        relation_nodes.append((relation, source, target))

    normalized_topic = topic.strip().casefold()
    seeds = tuple(
        sorted(
            (
                node
                for node, (title, _domain) in node_details.items()
                if normalized_topic
                and (
                    title.casefold() == normalized_topic
                    or node.document_key.casefold() == normalized_topic
                )
            ),
            key=lambda node: (node.document_kind, node.document_key),
        )
    )
    if not seeds:
        return _WikiKeywordExpansion((), "empty", False, ("일치하는 Seed가 없습니다.",))

    organization_nodes = {
        node
        for node, (_title, domain) in node_details.items()
        if str(domain or "").casefold() == "organization"
    }
    edges: list[WikiGraphExpansionEdge] = []
    for relation, source, target in relation_nodes:
        # 기존 1-hop과 같이 조직은 보조 검색어·중간 경로에서 제외한다. 단, 사용자가
        # 조직 자체를 주제로 요청한 경우 그 Seed에서 비조직 이웃으로 나가는 길은 둔다.
        if (source in organization_nodes and source not in seeds) or (
            target in organization_nodes and target not in seeds
        ):
            continue
        edges.append(
            WikiGraphExpansionEdge(
                source=source,
                target=target,
                relation_type=relation.relation_type,
                status=relation.status,
                review_status=relation.review_status,
                provenance_kind=relation.provenance_kind,
                confidence=relation.confidence,
                weight=relation.weight,
                supported=relation.supported,
            )
        )

    ranked_by_node: dict[WikiNodeIdentity, tuple[float, int]] = {}
    modes: set[str] = set()
    gate_passed = False
    maturity_reasons: list[str] = []
    for seed in seeds:
        result = expand_wiki_graph(seed, edges, top_k=top_k, fallback="one_hop")
        modes.add(result.mode)
        gate_passed = gate_passed or result.gate_passed
        maturity_reasons.extend(result.maturity.reasons)
        for score in result.scores:
            if score.node in seeds:
                continue
            current = ranked_by_node.get(score.node)
            candidate = (score.score, score.hops)
            if current is None or candidate[0] > current[0] or (
                candidate[0] == current[0] and candidate[1] < current[1]
            ):
                ranked_by_node[score.node] = candidate

    ranked_nodes = sorted(
        ranked_by_node,
        key=lambda node: (
            -ranked_by_node[node][0],
            ranked_by_node[node][1],
            node.document_kind,
            node.document_key,
        ),
    )
    keywords: list[str] = []
    seen_titles: set[str] = {normalized_topic}
    for node in ranked_nodes:
        title, domain = node_details.get(node, ("", None))
        marker = title.casefold()
        if (
            not title
            or marker in seen_titles
            or str(domain or "").casefold() == "organization"
        ):
            continue
        seen_titles.add(marker)
        keywords.append(title)
        if len(keywords) >= top_k:
            break

    if "bounded_ppr" in modes:
        mode = "bounded_ppr"
    elif keywords and "one_hop" in modes:
        mode = "one_hop"
    else:
        mode = "empty"
    return _WikiKeywordExpansion(
        keywords=tuple(keywords),
        mode=mode,
        gate_passed=gate_passed,
        maturity_reasons=tuple(dict.fromkeys(maturity_reasons)),
    )


async def _load_related_keyword_expansion(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    topic: str,
    top_k: int,
) -> _WikiKeywordExpansion:
    """권위 Graph Snapshot을 조회하고 조회 실패 때만 기존 1-hop으로 폴백한다."""
    if top_k <= 0:
        return _WikiKeywordExpansion((), "empty", False)
    try:
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=user_id)
            snapshot = await list_wiki_graph_relation_snapshot(
                connection,
                namespace_key=f"user/{user_id}",
            )
    except Exception as error:  # noqa: BLE001 - Migration 전 1-hop 운영 호환
        logger.warning(
            "Wiki Graph Snapshot 조회 실패, 기존 1-hop으로 폴백한다 "
            "(topic=%s): %s",
            topic,
            error,
        )
        related = None
        for lifecycle_aware in (True, False):
            try:
                async with connection.transaction():
                    await set_personal_wiki_scope(connection, user_id=user_id)
                    related = await list_related_wiki_keywords(
                        connection,
                        user_id=user_id,
                        topic=topic,
                        limit=top_k,
                        lifecycle_aware=lifecycle_aware,
                    )
                break
            except Exception as fallback_error:  # noqa: BLE001 - 운영 폴백 격리
                if lifecycle_aware:
                    logger.warning(
                        "Wiki lifecycle 1-hop 조회도 실패해 구버전 Schema SQL을 "
                        "재시도한다 (topic=%s): %s",
                        topic,
                        fallback_error,
                    )
                    continue
                logger.warning(
                    "Wiki 기존 1-hop 조회도 실패해 원 키워드로 진행한다 "
                    "(topic=%s): %s",
                    topic,
                    fallback_error,
                )
        if related is None:
            return _WikiKeywordExpansion((), "empty", False)
        return _WikiKeywordExpansion(
            tuple(item.title for item in related[:top_k]),
            "legacy_one_hop",
            False,
            ("Graph Snapshot 조회 실패",),
        )

    try:
        return _expand_wiki_graph_keywords(topic, snapshot, top_k=top_k)
    except Exception as error:  # noqa: BLE001 - 계산 실패는 원 키워드로 격리
        logger.warning(
            "Wiki Graph 확장 계산 실패, 원 키워드로 진행한다 (topic=%s): %s",
            topic,
            error,
        )
        return _WikiKeywordExpansion((), "empty", False, ("Graph 확장 계산 실패",))


def _report_topics(state: ReportGenerationState) -> list[str]:
    """이 리포트가 다룰 주제 목록을 돌려준다.

    topics가 비어 있으면 기존처럼 topic 하나만 다룬다. topics가 있으면 topic은
    카드 제목·generation_topic 용도로만 남고 본문이 다루는 주제는 이 목록이다.
    """
    topics = [str(topic).strip() for topic in (state.get("topics") or [])]
    return [topic for topic in topics if topic] or [state["topic"]]


def _report_context_identity(document: Any) -> str:
    """주제별로 다시 매겨지는 참조 번호 대신 원본 문서의 안정 식별자를 만든다."""
    version_id = str(getattr(document, "document_version_id", "") or "")
    chunk_id = str(getattr(document, "chunk_id", "") or "")
    if version_id or chunk_id:
        return f"version:{version_id}:chunk:{chunk_id}"
    url = str(getattr(document, "url", "") or "")
    if url:
        return f"url:{url}"
    return str(getattr(document, "reference", None) or document)


def _topic_bundle(
    state: ReportGenerationState, topic: str
) -> dict[str, object] | None:
    """주제에 연결된 관심사 범주 묶음을 찾는다.

    INTEREST_BUNDLE 요청은 접수 시 고정한 state["interest_bundle"]을 그 요청의
    대표 주제(state["topic"])에만 쓴다. SINGLE_TOPIC/topics 요청은 INT-013으로
    매칭된 주제만 state["topic_interest_bundles"]에서 찾는다 — 매칭 안 된 주제는
    키 자체가 없어 None을 받는다(interest-bundle-report-design.md §9).
    """
    if state.get("generation_scope") == "INTEREST_BUNDLE" and topic == state["topic"]:
        bundle = state.get("interest_bundle")
        return bundle if bundle else None
    return (state.get("topic_interest_bundles") or {}).get(topic)


def _bundle_search_keywords(bundle: dict[str, object] | None) -> list[str]:
    """묶음 Payload에서 루트 우선 검색 키워드 목록을 반환한다."""
    if not bundle:
        return []
    return [
        str(keyword) for keyword in bundle.get("keywords") or () if str(keyword).strip()
    ]


def _bundle_wiki_version_ids(bundle: dict[str, object] | None) -> list[str]:
    """관심사 Bundle에서 루트·이웃 Wiki Page Version ID를 순서대로 꺼낸다."""
    if not bundle:
        return []
    root = bundle.get("root")
    root_documents = root.get("documents") if isinstance(root, dict) else ()
    raw_items = [
        *(root_documents or ()),
        *(bundle.get("neighbors") or ()),
    ]
    version_ids: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        version_id = str(raw.get("document_version_id") or "").strip()
        if not version_id or version_id in seen:
            continue
        seen.add(version_id)
        version_ids.append(version_id)
    return version_ids[:6]


def build_report_generation_graph(connection: AsyncConnection[DictRow]) -> Any:
    """리포트 생성기 콘텐츠 생성 노드와 엣지를 조립해 컴파일된 그래프를 반환한다.

    load_context → generate → persist 순서로 검색·생성·영속화를 잇는다.
    """

    async def research(state: ReportGenerationState) -> dict[str, Any]:
        """조사원 에이전트가 도구를 골라 가며 근거 자료를 모은다.

        LLM이 Navigator의 wiki_search·wiki_read로 개인 Wiki Seed를 고르고,
        search_pool로 Global 자료를 찾는다. 실패하거나 한 건도 못 모으면 빈
        목록을 돌려주고 load_context가 기존 고정 경로로 되돌아간다.

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
        research_stats: list[dict[str, Any]] = []
        research_stats_by_topic: dict[str, dict[str, Any]] = {}
        outcomes_by_topic: dict[str, Any] = {}
        live_keywords_by_topic: dict[str, list[str]] = {}
        completed_topics: list[str] = []
        collected_live = False
        read_pipeline_version = str(
            state.get("read_pipeline_version") or LEGACY_READ_PIPELINE_VERSION
        )
        for topic in topics:
            intents[topic] = await to_thread(
                resolve_topic_intent, topic, state["user_id"]
            )
            documents_by_topic[topic] = []
            if (
                read_pipeline_version == LEGACY_READ_PIPELINE_VERSION
                and not research_agent_enabled()
            ):
                continue
            topic_started = monotonic()
            try:
                research_kwargs: dict[str, Any] = {
                    "topic": topic,
                    "user_id": state["user_id"],
                    "topic_intent": intents[topic],
                    "model": state["model"],
                    "wiki_version_id": state.get("wiki_version_id"),
                    "job_id": state["job_id"],
                }
                navigation_snapshot = (
                    state.get("wiki_navigation_snapshots") or {}
                ).get(topic)
                if navigation_snapshot:
                    research_kwargs["navigation_snapshot"] = navigation_snapshot
                topic_bundle = _topic_bundle(state, topic)
                bundle_keywords = _bundle_search_keywords(topic_bundle)
                if bundle_keywords:
                    research_kwargs["planned_queries"] = [
                        keyword
                        for keyword in bundle_keywords
                        if keyword.casefold() != topic.casefold()
                    ]
                planned_versions = _bundle_wiki_version_ids(topic_bundle)
                if planned_versions:
                    research_kwargs["planned_wiki_version_ids"] = planned_versions
                if read_pipeline_version == LEGACY_READ_PIPELINE_VERSION:
                    outcome = await asyncio.wait_for(
                        research_context(connection, **research_kwargs),
                        timeout=_TOPIC_RESEARCH_TIMEOUT_SECONDS,
                    )
                else:
                    outcome = await asyncio.wait_for(
                        research_context_for_version(
                            connection,
                            pipeline_version=read_pipeline_version,
                            defer_live=len(topics) > 1,
                            **research_kwargs,
                        ),
                        timeout=_TOPIC_RESEARCH_TIMEOUT_SECONDS,
                    )
            except TimeoutError:
                logger.warning(
                    "주제별 조사 실행 시간 초과(%.1f초), 기존 경로로 폴백: topic=%s",
                    _TOPIC_RESEARCH_TIMEOUT_SECONDS,
                    topic,
                )
                continue
            except Exception:
                # 주제 하나가 실패해도 나머지 주제는 계속 조사한다. 실패한 주제는
                # load_context가 고정 경로로 다시 시도한다.
                logger.exception(
                    "조사원 실행에 실패해 기존 수집 경로로 되돌립니다: topic=%s", topic
                )
                continue
            completed_topics.append(topic)
            outcomes_by_topic[topic] = outcome
            live_keywords_by_topic[topic] = list(
                research_kwargs.get("planned_queries") or []
            )
            documents_by_topic[topic] = list(outcome.documents)
            collected_live = collected_live or outcome.collected_live
            # 조사 노드가 리포트 시간의 대부분을 쓰는데 안이 안 보였다
            # (2026-08-11 실측: 336초 중 320초). 도구별 호출 수·소요 시간을
            # 작업 결과까지 실어 서버 로그 없이 확인한다.
            topic_stats = {
                "topic": topic,
                "pipeline_version": read_pipeline_version,
                "elapsed_ms": int((monotonic() - topic_started) * 1000),
                "tools": [
                    {"tool": name, "calls": count, "elapsed_ms": elapsed}
                    # 도구 통계가 없는 형태(테스트 더미 등)도 그대로 통과시킨다.
                    for name, count, elapsed in getattr(outcome, "tool_stats", ())
                ],
                "stop_reason": str(getattr(outcome, "stop_reason", "")),
                "documents": len(outcome.documents),
            }
            research_stats.append(topic_stats)
            research_stats_by_topic[topic] = topic_stats
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

        deferred_topics = [
            topic
            for topic in topics
            if bool(getattr(outcomes_by_topic.get(topic), "requires_live", False))
        ][:_MAX_LIVE_COLLECT_TOPICS]

        async def collect_deferred_live(
            topic: str,
        ) -> tuple[str, list[Any], int]:
            """V2 DB 단계를 마친 주제의 Live 근거를 DB 연결 없이 병렬 수집한다."""
            started = monotonic()
            documents: list[Any] = []
            try:
                kwargs: dict[str, object] = {"model": state["model"]}
                if live_keywords_by_topic.get(topic):
                    kwargs["related_keywords"] = live_keywords_by_topic[topic]
                documents = await to_thread(
                    collect_live_context,
                    topic,
                    state["user_id"],
                    **kwargs,
                )
            except Exception:
                logger.exception(
                    "V2 다중 주제 실시간 수집 실패, 저장 근거만 사용합니다: topic=%s",
                    topic,
                )
            return topic, documents, int((monotonic() - started) * 1000)

        if deferred_topics:
            deferred_results = await asyncio.gather(
                *(collect_deferred_live(topic) for topic in deferred_topics)
            )
            for topic, live_documents, elapsed_ms in deferred_results:
                outcome = outcomes_by_topic[topic]
                documents = merge_context_documents(
                    outcome.documents,
                    live_documents,
                )
                outcomes_by_topic[topic] = replace(
                    outcome,
                    documents=tuple(documents),
                    collected_live=True,
                    requires_live=False,
                    tool_stats=(
                        *outcome.tool_stats,
                        ("collect_live_parallel", 1, elapsed_ms),
                    ),
                )
                documents_by_topic[topic] = list(documents)
                collected_live = True
                topic_stats = research_stats_by_topic[topic]
                topic_stats["documents"] = len(documents)
                topic_stats["parallel_live_elapsed_ms"] = elapsed_ms
                topic_stats["tools"].append(
                    {
                        "tool": "collect_live_parallel",
                        "calls": 1,
                        "elapsed_ms": elapsed_ms,
                    }
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
            "research_completed_topics": completed_topics,
            "research_notes": "\n".join(notes),
            "research_collected_live": collected_live,
            "research_calls": calls,
            "research_stats": research_stats,
        }

    def _topic_context_hint(documents: Sequence[Any], topic: str) -> str:
        """이미 조회한 문서에서 이 주제가 무엇인지 알려줄 한 줄을 뽑는다.

        주제어만으로는 보조 검색어가 헛돈다(2026-08-11 실측: `코리`에 "최신 뉴스",
        "활동 소식"이 생성됐다 — 제약 기업인지 모르니 아무 데나 붙는 말이 나왔다).
        개인 Wiki 문서에 그 설명이 이미 들어 있으므로 DB를 다시 부르지 않는다.
        """
        marker = "".join(topic.split()).casefold()
        for document in documents:
            title = str(getattr(document, "title", "") or "")
            if "".join(title.split()).casefold() != marker:
                continue
            content = " ".join(str(getattr(document, "content", "") or "").split())
            if content:
                return content[:200]
        return ""

    async def load_related_keywords(
        user_id: str, topic: str, *, intent: str = "news", context: str = ""
    ) -> list[str]:
        """개인 Wiki Graph Gate로 bounded PPR 또는 검증 1-hop 키워드를 읽는다.

        관심 키워드 하나로만 수집하면 '코스피' 리포트에 코스닥시장 기사가 걸리지
        않는데, 그 연결은 Wiki Builder가 이미 저장해 둔 것이다.

        Snapshot 조회가 성공하면 active·accepted·active support·provenance별
        confidence Gate를 통과한 Edge만 쓴다. 성숙한 Graph는 2-hop bounded PPR,
        Gate 실패 Graph는 검증 1-hop/empty를 사용한다. Migration 미적용 등
        Snapshot 조회 실패 때만 배포 호환을 위해 기존 1-hop SQL로 폴백한다.

        Args:
            user_id: 조회 대상 사용자 ID
            topic: 리포트 주제로 들어온 관심 키워드

        Returns:
            연결 강도 내림차순 이웃 키워드 제목. 확장이 꺼져 있거나 실패하면 빈 목록.
        """
        limit = related_keyword_fetch_limit()
        if limit <= 0:
            return []
        expansion = await _load_related_keyword_expansion(
            connection,
            user_id=user_id,
            topic=topic,
            top_k=limit,
        )
        logger.info(
            "Wiki Graph 확장 %d건 (topic=%s, mode=%s, gate=%s, 이웃=%s, 사유=%s)",
            len(expansion.keywords),
            topic,
            expansion.mode,
            expansion.gate_passed,
            list(expansion.keywords),
            list(expansion.maturity_reasons),
        )
        keywords = list(expansion.keywords)
        # 이웃이 모자란 자리만 보조 검색어로 채운다. 방금 생긴 관심사는 Wiki에
        # 이웃이 없어 주제어 하나로만 수집하는데, 그런 주제일수록 창고도 얕아
        # 결과가 홍보성 자료로 채워진다(2026-08-11 실측: '다낭 여행').
        # 이웃이 충분하면 부르지 않는다 — LLM 호출을 아낀다.
        if len(keywords) < limit:
            facets = await to_thread(
                generate_topic_facets,
                topic,
                intent=intent,
                context=context,
                limit=min(_MAX_TOPIC_FACETS, limit - len(keywords)),
            )
            existing = {"".join(topic.split()).casefold()} | {
                "".join(keyword.split()).casefold() for keyword in keywords
            }
            keywords.extend(
                facet
                for facet in facets
                if "".join(facet.split()).casefold() not in existing
            )
        return keywords

    async def load_bundle_navigation_context(
        state: ReportGenerationState,
        *,
        topic: str,
        bundle: dict[str, object] | None,
    ) -> list[Any]:
        """관심사 Bundle의 고정 Version을 Navigator Packet으로 읽는다."""
        version_ids = _bundle_wiki_version_ids(bundle)
        if not version_ids:
            return []
        packet = await wnav_006(
            connection,
            user_id=state["user_id"],
            query=topic,
            selected_document_version_ids=version_ids,
            wiki_version_id=state.get("wiki_version_id"),
            max_depth=1,
            max_pages=6,
            max_chunks=12,
        )
        await persist_report_navigation_snapshot(
            connection,
            user_id=state["user_id"],
            job_id=state["job_id"],
            topic=topic,
            packets=[packet],
        )
        return navigation_packet_documents(packet, user_id=state["user_id"])

    async def load_context(state: ReportGenerationState) -> dict[str, Any]:
        """조사원이 모은 자료를 생성용 Context로 다듬는다.

        관심사 Bundle이면(INTEREST_BUNDLE 요청이거나, SINGLE_TOPIC/topics 요청의
        주제가 INT-013으로 활성 관심사와 매칭됐으면) Job 접수 시 고정한 Wiki
        Version을 먼저 읽어 생성 Context에 보장한다. 조사원이 자료를 모았으면 그
        뒤에 합치고, 비었으면 기존 고정 경로(개인 Wiki 조회 → 풀 판정 → 부족하면
        실시간 수집)를 수행한다.
        """
        topics = _report_topics(state)
        if len(topics) > 1:
            return await _load_multi_topic_contexts(state, topics)
        researched = list(state.get("research_documents") or [])
        topic_bundle = _topic_bundle(state, state["topic"])
        navigator_used = any(
            str(getattr(document, "context_role", "")).startswith("wiki_navigator_")
            for document in researched
        )
        pinned_wiki = (
            (
                await load_bundle_navigation_context(
                    state, topic=state["topic"], bundle=topic_bundle
                )
                if not researched and research_agent_enabled()
                else await load_pinned_wiki_context(
                    connection,
                    user_id=state["user_id"],
                    interest_bundle=topic_bundle,
                )
            )
            if topic_bundle and not navigator_used
            else []
        )
        if researched:
            logger.info(
                "조사원 자료 사용: topic=%s %d건, 고정 Wiki %d건 (도구 호출 %d회)",
                state["topic"],
                len(researched),
                len(pinned_wiki),
                len(state.get("research_calls") or []),
            )
            research_contexts = (
                merge_context_documents(pinned_wiki, researched)
                if pinned_wiki
                else researched
            )
            return await _finalize_contexts(state, research_contexts)
        bundle_keywords = _bundle_search_keywords(topic_bundle)
        search_queries = bundle_keywords or [state["topic"]]
        if research_agent_enabled():
            search_groups = [
                await search_global_documents(
                    connection,
                    user_id=state["user_id"],
                    query=query,
                    topic_intent=str(state.get("topic_intent") or "news"),
                )
                for query in search_queries
            ]
            groups = [pinned_wiki, *search_groups] if pinned_wiki else search_groups
            hybrid = (
                merge_context_documents(*groups)
                if len(groups) > 1
                else list(groups[0])
            )
            pool_freshness: dict[str, Any] = {}
        else:
            query_embeddings = await to_thread(embed_wiki_queries, search_queries)
            async with connection.transaction():
                await set_personal_wiki_scope(connection, user_id=state["user_id"])
                search_groups = [
                    await prag_003(
                        connection,
                        user_id=state["user_id"],
                        query=query,
                        query_embedding=query_embeddings.get(query),
                    )
                    for query in search_queries
                ]
                groups = (
                    [pinned_wiki, *search_groups] if pinned_wiki else search_groups
                )
                hybrid = (
                    merge_context_documents(*groups)
                    if len(groups) > 1
                    else list(groups[0])
                )
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
        related_keywords = []
        if not skip_live:
            related_keywords = (
                bundle_keywords[1:]
                if topic_bundle
                else await load_related_keywords(
                    state["user_id"],
                    state["topic"],
                    intent=str(state.get("topic_intent") or "news"),
                    context=_topic_context_hint(personal_documents, state["topic"]),
                )
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

    async def _topic_documents(
        state: ReportGenerationState,
        topic: str,
        *,
        allow_live: bool,
        timings: dict[str, int] | None = None,
    ) -> tuple[list[Any], bool]:
        """주제 하나가 쓸 근거 문서를 모은다(여러 주제를 묶는 경로 전용).

        조사원이 그 주제로 모은 자료를 우선 쓰고, 빈손이면 창고를 다시 검색한다.
        창고가 부족하면 단일 주제 경로와 **같은 규칙으로** 실시간 수집을 돈다.

        처음 만들 때는 실시간 수집을 아예 뺐다. "조사원이 이미 수집 기회를 한 번
        썼다"고 봤는데 틀렸다 — 조사원에게는 search_pool만 주고 collect_live는
        도구로 노출하지 않는다(researcher.py). 그래서 창고에 없는 주제는 영영
        근거가 0건이었다(2026-08-10 실측: '환율' 섹션이 통째로 빠졌다).

        접수 시 INT-013으로 이 주제가 활성 관심사와 매칭됐으면(`_topic_bundle`)
        고정 Wiki Version과 묶음 키워드로 검색한다. 매칭 안 됐으면 주제 문자열
        하나로만 검색한다(interest-bundle-report-design.md §9).

        Args:
            allow_live: 이 리포트에 실시간 수집 예산이 남았는지. 주제마다 외부
                수집을 돌리면 Worker lease(600초)를 넘길 수 있어 호출자가 제한한다.

        Returns:
            (근거 문서 목록, 실시간 수집을 실제로 돌렸는지). 뒤엣값으로 호출자가
            예산을 깎는다 — 창고로 해결된 주제까지 예산을 먹으면, 정작 수집이
            필요한 뒤쪽 주제가 못 돈다.
        """
        researched = list(
            (state.get("research_documents_by_topic") or {}).get(topic) or []
        )
        if researched or topic in set(state.get("research_completed_topics") or []):
            return researched, False

        def _record(stage: str, since: float) -> None:
            """단계별 소요 시간을 밀리초로 기록한다.

            어디서 시간이 가는지 서버 로그 없이 확인하려고 남긴다(2026-08-11
            실측: 3주제 리포트가 1615초 걸렸는데 본문 생성은 5.2초였다).
            """
            if timings is not None:
                timings[stage] = int((monotonic() - since) * 1000)

        search_started = monotonic()
        topic_bundle = _topic_bundle(state, topic)
        pinned_wiki = (
            (
                await load_bundle_navigation_context(
                    state, topic=topic, bundle=topic_bundle
                )
                if research_agent_enabled()
                else await load_pinned_wiki_context(
                    connection, user_id=state["user_id"], interest_bundle=topic_bundle
                )
            )
            if topic_bundle
            else []
        )
        bundle_keywords = _bundle_search_keywords(topic_bundle)
        search_queries = bundle_keywords or [topic]
        if research_agent_enabled():
            search_groups = [
                await search_global_documents(
                    connection,
                    user_id=state["user_id"],
                    query=query,
                    topic_intent=str(
                        (state.get("topic_intents") or {}).get(topic) or "news"
                    ),
                )
                for query in search_queries
            ]
            groups = [pinned_wiki, *search_groups] if pinned_wiki else search_groups
            hybrid = (
                merge_context_documents(*groups)
                if len(groups) > 1
                else list(groups[0])
            )
            pool_freshness: dict[str, Any] = {}
        else:
            query_embeddings = await to_thread(embed_wiki_queries, search_queries)
            async with connection.transaction():
                await set_personal_wiki_scope(connection, user_id=state["user_id"])
                search_groups = [
                    await prag_003(
                        connection,
                        user_id=state["user_id"],
                        query=query,
                        query_embedding=query_embeddings.get(query),
                    )
                    for query in search_queries
                ]
                groups = (
                    [pinned_wiki, *search_groups] if pinned_wiki else search_groups
                )
                hybrid = (
                    merge_context_documents(*groups)
                    if len(groups) > 1
                    else list(groups[0])
                )
                pool_freshness = await load_global_document_freshness(
                    connection,
                    [
                        str(getattr(document, "document_version_id", "") or "")
                        for document in hybrid
                    ],
                )
        _record("search", search_started)
        intents = state.get("topic_intents") or {}
        topic_intent = str(intents.get(topic) or "news")
        # 단일 주제 경로와 같은 하한을 쓴다. 여기에만 하한이 없으면 0점짜리
        # Wiki 목차 조각이 근거로 들어온다.
        # 주제마다 근거 몫이 몇 건뿐이라 상대 비율(최고점의 75%)을 쓰지 않는다.
        # 후보가 적으면 그 컷이 최고점 하나만 남기고 나머지를 통째로 잘라낸다
        # (2026-08-10 실측: 단일 주제 '환율'은 창고에서 근거 3건을 붙였는데 여러
        # 주제 경로에서는 0건이었다). 절대 하한과 신선도는 그대로 적용한다.
        pool_documents = select_pool_documents(
            hybrid,
            published_at=pool_freshness,
            topic_intent=topic_intent,
            score_ratio=0.0,
        )
        stored = [*select_personal_documents(hybrid), *pool_documents]
        # 단일 주제 경로와 같은 판정이다 — 창고에 확실히 쓸 만한 자료가 있으면
        # 외부 수집을 건너뛴다. 대부분의 주제가 여기서 끝난다.
        relevance_started = monotonic()
        pool_is_usable = is_pool_sufficient(pool_documents) and await to_thread(
            is_pool_relevant, topic, pool_documents
        )
        _record("relevance", relevance_started)
        if pool_is_usable:
            return stored, False
        if not allow_live:
            logger.info(
                "실시간 수집 생략: topic=%s 이번 리포트의 수집 예산을 다 썼다.", topic
            )
            return stored, False
        # 단일 주제 경로와 같은 확장이다. 주제 이름 하나로만 수집하면 '코스피'
        # 리포트에 코스닥시장 기사가 안 걸리는데, 그 연결은 Wiki Builder가 이미
        # 저장해 둔 것이다. 수집을 실제로 돌 때만 조회한다 — 건너뛸 거면 DB 왕복이
        # 낭비다. 이미 매칭된 묶음이 있으면 그 이웃 키워드를 그대로 쓴다.
        keywords_started = monotonic()
        related_keywords = (
            bundle_keywords[1:]
            if topic_bundle
            else await load_related_keywords(
                state["user_id"],
                topic,
                intent=topic_intent,
                context=_topic_context_hint(stored, topic),
            )
        )
        _record("related_keywords", keywords_started)
        live_started = monotonic()
        try:
            live = await asyncio.wait_for(
                to_thread(
                    collect_live_context,
                    topic,
                    state["user_id"],
                    model=state["model"],
                    related_keywords=related_keywords,
                ),
                timeout=_TOPIC_RESEARCH_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "주제별 실시간 수집 시간 초과(%.1f초): topic=%s",
                _TOPIC_RESEARCH_TIMEOUT_SECONDS,
                topic,
            )
            live = []
        _record("live_collect", live_started)
        logger.info(
            "주제별 실시간 수집: topic=%s %d건 (이웃 키워드 %d개)",
            topic,
            len(live),
            len(related_keywords),
        )
        return [*stored, *live], True

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
        covered: list[str] = []
        by_topic: dict[str, list[Any]] = {}
        evidence_trace: list[dict[str, Any]] = []
        live_budget = _MAX_LIVE_COLLECT_TOPICS
        for topic in topics:
            elapsed: dict[str, int] = {}
            topic_started = monotonic()
            documents, collected_live = await _topic_documents(
                state, topic, allow_live=live_budget > 0, timings=elapsed
            )
            # 창고로 해결된 주제는 예산을 쓰지 않는다. 무조건 깎으면 앞 주제들이
            # 수집을 한 번도 안 했는데도 뒤쪽 주제가 예산 부족으로 못 돈다.
            if collected_live:
                live_budget -= 1
            # 근거를 생성에 넘기기 전에 주제에 해당하는 문장만 남긴다. 기사 하나가
            # 여러 사안을 실으면 본문이 주제 밖 사실까지 옮겨 적는다(2026-08-11
            # 실측: '폭염' 섹션이 같은 기사의 KIA 성적을 그대로 썼다).
            gathered = len(documents)
            focus_started = monotonic()
            documents = await to_thread(
                focus_documents_on_topic, topic, documents, model=state["model"]
            )
            elapsed["focus"] = int((monotonic() - focus_started) * 1000)
            focused = len(documents)
            # 앞 주제가 이미 가져간 문서는 **상한을 적용하기 전에** 뺀다. 뒤에서
            # 거르면 상한이 중복 문서로 다 차서, 그 주제만의 근거가 남아 있어도
            # 확보 0건이 되어 섹션이 통째로 빠진다(2026-08-11 실측: '폭염'이 근거를
            # 7건 모으고 선별도 통과했는데 상한 4건이 전부 '코스닥'과 겹쳐 사라졌다).
            #
            # 겹친 문서를 그냥 두 주제에 같이 쓸 수는 없다. focus가 앞 주제 기준으로
            # 본문을 이미 잘라놔서, 뒤 주제가 그 문서를 인용하면 자기 주제와 무관한
            # 문장을 근거로 삼게 된다.
            documents = [
                document
                for document in documents
                if _report_context_identity(document) not in seen
            ]
            deduped = len(documents)
            finalize_started = monotonic()
            finalized = await _finalize_contexts(state, documents, max_documents=quota)
            elapsed["finalize"] = int((monotonic() - finalize_started) * 1000)
            selected = len(finalized.get("contexts", []))
            picked = 0
            for context in finalized.get("contexts", []):
                key = _report_context_identity(context)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(context)
                by_topic.setdefault(topic, []).append(context)
                picked += 1
            if picked:
                covered.append(topic)
            # 단계별 건수를 작업 결과에 남긴다. 섹션이 빠졌을 때 어디서 근거를
            # 잃었는지 서버 로그 없이 확인하려면 이 값이 필요하다(2026-08-11:
            # '폭염' 섹션이 사라진 원인을 못 찾아 리포트를 네 번 다시 돌렸다).
            evidence_trace.append(
                {
                    "topic": topic,
                    "gathered": gathered,
                    "after_focus": focused,
                    "after_dedupe": deduped,
                    "selected": selected,
                    "picked": picked,
                    "quota": quota,
                    "collected_live": collected_live,
                    "elapsed_ms": {
                        **elapsed,
                        "total": int((monotonic() - topic_started) * 1000),
                    },
                }
            )
            logger.info(
                "주제별 근거 배정: topic=%s 몫=%d건 수집=%d건 선별후=%d건 "
                "중복제외후=%d건 확보=%d건 %dms %s",
                topic,
                quota,
                gathered,
                focused,
                deduped,
                picked,
                int((monotonic() - topic_started) * 1000),
                elapsed,
            )
        if not merged:
            raise RuntimeError("여러 주제 리포트에 쓸 근거를 한 건도 모으지 못했습니다.")
        if len(covered) < len(topics):
            # 근거를 한 건도 못 구한 주제는 생성 프롬프트에서 뺀다. 남겨 두면
            # "소주제를 순서대로 빠짐없이 다루라"는 지시 때문에 근거 없는 일반론으로
            # 그 섹션을 채운다(2026-08-10 실측: '환율' 섹션이 "구체적인 정보는
            # 제공되지 않았습니다. 그러나 변동성이 높아지고 있는 상황이므로..."가 됐다).
            logger.info(
                "근거 없는 주제를 생성에서 제외: %s",
                ", ".join(topic for topic in topics if topic not in covered),
            )
        return {
            "contexts": merged,
            "covered_topics": covered,
            "contexts_by_topic": by_topic,
            "evidence_trace": evidence_trace,
        }

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
        generation_kwargs: dict[str, Any] = {
            "topic": state["topic"],
            # 근거를 못 구한 주제는 빼고 넘긴다(load_context가 추린다).
            "topics": state.get("covered_topics") or _report_topics(state),
            "content_type": state["content_type"],
            "language": state["language"],
            "contexts": state["contexts"],
            "model": state["model"],
            "correction": str(state.get("review_correction") or ""),
        }
        if state.get("generation_scope") == "INTEREST_BUNDLE":
            generation_kwargs["interest_bundle"] = state.get("interest_bundle")
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
                        **generation_kwargs,
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

    def route_after_context(state: ReportGenerationState) -> str:
        """변경점 추적 토글에 따라 기존 생성과 델타 경로 중 하나를 고른다.

        토글이 꺼져 있으면(기본값) 지금까지와 완전히 같은 generate 경로다.
        요청이 켜도 서버 차단 스위치(CHANGE_HISTORY_ENABLED=0)가 우선한다 —
        델타 경로에 장애가 나도 리포트 발행 자체는 멈추면 안 되기 때문이다.
        """
        if state.get("change_history_enabled") and change_history_available():
            return "change_history"
        return "generate"

    def _delta_topics(state: ReportGenerationState) -> list[str]:
        """델타를 따로 돌릴 주제 목록을 정한다.

        여러 주제를 묶는 요청은 근거를 실제로 확보한 주제(covered_topics)만
        비교한다 — 근거 0건인 주제로 델타를 돌리면 매번 "변화 없음"만 쌓인다.
        """
        topics = _report_topics(state)
        if len(topics) <= 1:
            return topics
        covered = [topic for topic in (state.get("covered_topics") or []) if topic]
        return covered or topics

    async def _multi_topic_change_history(
        state: ReportGenerationState, topics: list[str]
    ) -> dict[str, Any]:
        """주제마다 델타를 따로 돌리고 하나의 본문으로 합친다.

        비교축이 (user_id, topic)이라 여러 주제를 한 축으로 묶으면 주제별 변화가
        구분되지 않는다(팩트가 대표 문자열 하나에 섞여 쌓인다).

        asyncio.gather와 Semaphore(3)로 주제별 델타를 동시 병렬 처리하여 지연 시간을 단축한다.
        단일 DB connection 상의 트랜잭션 충돌을 방지하기 위해 db_lock을 전달한다.
        """
        contexts_by_topic = state.get("contexts_by_topic") or {}
        db_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(3)

        async def _run_topic_delta(topic: str) -> tuple[str, dict[str, Any] | None]:
            contexts = list(contexts_by_topic.get(topic) or [])
            if not contexts:
                return topic, None
            async with semaphore:
                try:
                    outcome = await chg_001(
                        connection,
                        user_id=state["user_id"],
                        job_id=state["job_id"],
                        topic=topic,
                        contexts=contexts,
                        model=state["model"],
                        db_lock=db_lock,
                    )
                    return topic, outcome
                except Exception:
                    logger.exception("주제 델타에 실패해 이 주제는 빼고 진행합니다: topic=%s", topic)
                    return topic, None

        results = await asyncio.gather(*[_run_topic_delta(t) for t in topics])
        collected: list[tuple[str, Any]] = []
        outcomes: list[dict[str, Any]] = []
        skipped: list[str] = []

        for topic, outcome in results:
            if outcome is None:
                skipped.append(topic)
            else:
                collected.append((topic, outcome["generated"]))
                outcomes.append(outcome)

        if not collected:
            logger.warning("모든 주제의 델타가 실패해 기존 생성 경로로 되돌립니다.")
            return {"change_history": {"failed": True}}
        generated = merge_topic_delta_reports(
            collected,
            topic=state["topic"],
            reference_date=current_reference_date(),
        )
        summary: dict[str, Any] = {
            "failed": False,
            "topics": [topic for topic, _ in collected],
            "skipped_topics": skipped,
            "is_first_run": all(bool(item.get("is_first_run")) for item in outcomes),
            "no_change": all(bool(item.get("no_change")) for item in outcomes),
        }
        for key in (
            "fact_count",
            "duplicate_count",
            "stored_fact_count",
            "input_tokens",
            "output_tokens",
        ):
            summary[key] = sum(int(item.get(key) or 0) for item in outcomes)
        summary["dropped_flags"] = [
            flag for item in outcomes for flag in (item.get("dropped_flags") or [])
        ]
        return {"generated": generated, "change_history": summary}

    async def change_history(state: ReportGenerationState) -> dict[str, Any]:
        """직전 보고서 이후의 변화를 판별해 델타 보고서를 만든다(generate 대체).

        서브그래프가 조립한 markdown을 기존 review 노드가 읽는 것과 **같은 키**
        (`generated`)에 넣어, 그대로 Critic 검증과 기존 persist로 이어지게 한다.

        주제가 여럿이면 주제마다 따로 돌려 합친다. 주제가 하나면 지금까지와
        완전히 같은 단일 호출이다(회귀 0).

        델타 경로가 실패하면 예외를 올리지 않고 기존 generate 경로로 되돌린다 —
        토글은 보고서를 더 낫게 만들려는 장치지, 켰다고 발행이 막히면 안 된다.
        """
        started = monotonic()
        # 주제가 하나로 줄어든 경우(나머지가 근거 부족)에도 묶음 경로로 보낸다 —
        # 그래야 대표 문자열이 아니라 실제 주제로 비교축이 잡힌다.
        if len(_report_topics(state)) > 1:
            result = await _multi_topic_change_history(state, _delta_topics(state))
            if "generated" not in result:
                return result
            result["review_correction"] = ""
            result["latency_ms"] = int((monotonic() - started) * 1000)
            return result
        try:
            outcome = await chg_001(
                connection,
                user_id=state["user_id"],
                job_id=state["job_id"],
                topic=state["topic"],
                contexts=list(state["contexts"]),
                model=state["model"],
            )
        except Exception:
            logger.exception("변경점 추적에 실패해 기존 생성 경로로 되돌립니다.")
            return {"change_history": {"failed": True}}
        summary = {key: value for key, value in outcome.items() if key != "generated"}
        summary["failed"] = False
        return {
            "generated": outcome["generated"],
            "review_correction": "",
            "latency_ms": int((monotonic() - started) * 1000),
            "change_history": summary,
        }

    def route_after_change_history(state: ReportGenerationState) -> str:
        """델타 경로가 보고서를 만들었으면 검토로, 실패했으면 기존 생성으로 보낸다."""
        change = state.get("change_history") or {}
        failed = bool(change.get("failed")) if isinstance(change, dict) else True
        return "generate" if failed else "review"

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
        """검토 결과에 따라 재작성으로 돌아갈지 저장으로 갈지 정한다.

        델타 경로로 만든 보고서는 재작성으로 돌리지 않는다. generate는 정형
        섹션과 before/after 수치를 모르는 from-scratch 생성이라, 여기로 되돌리면
        델타 보고서가 통째로 일반 리포트로 바뀐다 — 지적을 반영하는 게 아니라
        결과물의 성격이 달라지는 것이다. 검토자의 지적은 로그에 남기고 그대로
        발행한다(검토 재작성 상한에 닿았을 때와 같은 처리).
        """
        change = state.get("change_history") or {}
        from_delta = isinstance(change, dict) and change.get("failed") is False
        if from_delta and state.get("review_correction"):
            logger.info("델타 보고서라 재작성 없이 발행합니다(검토 지적은 로그에 남깁니다).")
            return "persist"
        return "generate" if state.get("review_correction") else "persist"

    async def persist(state: ReportGenerationState) -> dict[str, Any]:
        """생성 Run·후보·Citation·Snapshot·Outbox를 저장 Transaction으로 기록한다."""
        # 요청 토글이 아니라 델타 경로가 **실제로 이 본문을 만들었는지**를 판단해
        # 넘긴다. change_history 노드는 성공하면 summary.failed=False를 채우고,
        # 서버 차단 스위치로 아예 안 탔거나 실패해 generate()로 되돌아갔으면 이
        # 키 자체가 없거나 failed=True다 — 요청 파라미터를 그대로 읽으면
        # CHANGE_HISTORY_ENABLED=0일 때 값과 body 구조가 어긋난다(2026-08-11
        # 풀스택 피드백).
        change_history_result = state.get("change_history")
        change_history_used = isinstance(change_history_result, dict) and not bool(
            change_history_result.get("failed", True)
        )
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
                change_history_used=change_history_used,
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
        result = dict(safeguarded.data)
        # 주제별 근거 단계 건수를 결과에 실어 GET /jobs/{id}/result로 읽게 한다.
        # 서버 로그에 접근하지 않고도 어느 주제가 어느 단계에서 근거를 잃었는지
        # 확인할 수 있어야 한다.
        trace = state.get("evidence_trace")
        if trace:
            result["evidence_trace"] = list(trace)
        research_stats = state.get("research_stats")
        if research_stats:
            result["research_stats"] = list(research_stats)
        read_pipeline_version = str(
            state.get("read_pipeline_version") or LEGACY_READ_PIPELINE_VERSION
        )
        if read_pipeline_version != LEGACY_READ_PIPELINE_VERSION:
            result["read_pipeline_version"] = read_pipeline_version
        return {"result": result}

    graph = StateGraph(ReportGenerationState)
    graph.add_node("research", research)
    graph.add_node("load_context", load_context)
    graph.add_node("generate", generate)
    graph.add_node("change_history", change_history)
    graph.add_node("review", review)
    graph.add_node("persist", persist)
    graph.set_entry_point("research")
    graph.add_edge("research", "load_context")
    # 변경점 추적 토글이 켜지면 generate 대신 델타 서브그래프가 본문을 만든다.
    # 꺼져 있으면(기본값) 지금까지와 같은 load_context → generate 경로다.
    graph.add_conditional_edges(
        "load_context",
        route_after_context,
        {"generate": "generate", "change_history": "change_history"},
    )
    graph.add_conditional_edges(
        "change_history",
        route_after_change_history,
        {"review": "review", "generate": "generate"},
    )
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
    change_history_enabled: bool = False,
    generation_scope: str = "SINGLE_TOPIC",
    interest_bundle: dict[str, object] | None = None,
    topic_interest_bundles: dict[str, dict[str, object]] | None = None,
    wiki_version_id: str | None = None,
    wiki_navigation_snapshots: dict[str, dict[str, object]] | None = None,
    read_pipeline_version: str = LEGACY_READ_PIPELINE_VERSION,
) -> dict[str, object]:
    """Report Builder Generation 그래프를 실행하고 저장 결과 Payload를 반환한다.

    개발 API와 Worker가 공유하는 유일한 생성 실행 진입점이다.

    Args:
        change_history_enabled: 변경점(Delta) 추적 경로 사용 여부. 기본값은
            꺼짐이며, 꺼진 실행은 지금까지와 완전히 같은 경로를 탄다.
        topic_interest_bundles: SINGLE_TOPIC/topics 요청에서 접수 시 활성
            관심사와 매칭된 주제의 INT-012 스냅샷(키: 주제 문자열).
        wiki_version_id: Job 접수 시 고정한 활성 Wiki Build UUID
        wiki_navigation_snapshots: 첫 Reader 실행이 Topic별로 고정한 Packet Metadata
        read_pipeline_version: Job 접수 시 고정한 읽기 루프 버전. 과거 Job은 V1
    """
    graph = build_report_generation_graph(connection)
    state = await graph.ainvoke(
        {
            "user_id": user_id,
            "job_id": job_id,
            "attempt_number": attempt_number,
            "topic": topic,
            "topics": list(topics or []),
            "generation_scope": generation_scope,
            "interest_bundle": dict(interest_bundle or {}),
            "topic_interest_bundles": dict(topic_interest_bundles or {}),
            "wiki_version_id": wiki_version_id,
            "wiki_navigation_snapshots": dict(wiki_navigation_snapshots or {}),
            "read_pipeline_version": read_pipeline_version,
            "content_type": content_type,
            "language": language,
            "model": model,
            "change_history_enabled": change_history_enabled,
        }
    )
    return dict(state["result"])
