"""Personal Wiki V3 전체 재구성의 내부 단계를 LangGraph로 실행한다.

활성 원본을 먼저 고정한 뒤 원본별 온보딩 해석·분류·identity·관계·계획을
메모리에서 순차 실행한다. 전체 Snapshot 품질 Gate를 통과한 경우에만 하나의
Transaction에서 기존 Wiki를 교체하며, 원본이 없으면 별도 retire 경로로
검색 가능한 파생물을 안전하게 내린다.
"""

from __future__ import annotations

import logging
from asyncio import to_thread
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, NotRequired, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from psycopg import AsyncConnection

from agent.wiki_builder.models import (
    ExistingWikiEntry,
    WikiBuildPlan,
    WikiClassification,
    WikiDocumentPlan,
    WikiRelationPlan,
)
from infrastructure.persistence.api import (
    PersistedWikiBuild,
    UserSourceDocumentForAgent,
    list_cached_custom_topic_contexts,
    list_existing_wiki_entries,
    list_onboarding_topic_contexts,
    list_user_source_versions_for_rebuild,
    persist_wiki_build,
    retire_personal_wiki_without_sources,
    save_custom_topic_contexts,
    set_personal_wiki_scope,
    supersede_personal_wiki_for_rebuild,
    update_full_wiki_rebuild_summary,
)

from .classification import classify_source_for_wiki, classify_wiki_source
from .embeddings import wba_011
from .identity_resolution import (
    WikiIdentityResolutionResult,
    WikiResolutionDraft,
    prepare_wiki_identity_resolution,
    resolve_wiki_identity_conflicts,
    validate_wiki_identity_quality,
)
from .onboarding_contexts import resolve_onboarding_contexts
from .planning import build_wiki_plan
from .quality import WikiQualityReport, validate_wiki_quality
from .relation_candidates import WikiNodeIdentity
from .relation_linking import build_relation_candidate_sets, link_wiki_relations

type DictRow = dict[str, Any]
type WikiClassifier = Callable[..., WikiClassification]
type WikiRelationLinker = Callable[..., WikiClassification]

LANGGRAPH_FULL_REBUILD_VERSION = "langgraph_v3"

logger = logging.getLogger("agent.wiki_builder")


@dataclass(frozen=True, slots=True)
class WikiFullRebuildRuntimeContext:
    """V3 전체 재구성 노드가 공유하는 DB와 교체 가능한 LLM 경계."""

    connection: AsyncConnection[DictRow]
    classifier: WikiClassifier
    linker: WikiRelationLinker


class WikiFullRebuildState(TypedDict):
    """V3 전체 재구성 그래프가 원본 순회와 원자 저장 사이에 공유하는 상태."""

    user_id: str
    job_id: str
    model: str
    embedding_model: str
    embedding_batch_threshold: int
    generated_at: str
    sources: NotRequired[list[UserSourceDocumentForAgent]]
    source_index: NotRequired[int]
    current_source: NotRequired[UserSourceDocumentForAgent]
    resolution_existing_entries: NotRequired[list[ExistingWikiEntry]]
    onboarding_dependencies: NotRequired[dict[str, tuple[list[Any], list[Any]]]]
    onboarding_contexts: NotRequired[list[Any]]
    onboarding_context_model: NotRequired[str | None]
    generated_custom_contexts: NotRequired[list[Any]]
    existing_entities: NotRequired[list[ExistingWikiEntry]]
    existing_concepts: NotRequired[list[ExistingWikiEntry]]
    existing_relations: NotRequired[list[WikiRelationPlan]]
    onboarding_anchors: NotRequired[list[WikiNodeIdentity]]
    classification: NotRequired[WikiClassification]
    classification_model: NotRequired[str]
    resolution_draft: NotRequired[WikiResolutionDraft]
    identity_resolution: NotRequired[WikiIdentityResolutionResult | None]
    identity_model: NotRequired[str]
    relation_candidates: NotRequired[dict[str, Any]]
    relation_model: NotRequired[str]
    current_plan: NotRequired[WikiBuildPlan]
    staged: NotRequired[list[tuple[UserSourceDocumentForAgent, WikiBuildPlan]]]
    quality: NotRequired[WikiQualityReport]
    persisted: NotRequired[PersistedWikiBuild]
    superseded_document_count: NotRequired[int]
    embedding_count: NotRequired[int]
    embedding_warning: NotRequired[str | None]
    retirement_result: NotRequired[dict[str, int]]
    result: NotRequired[dict[str, object]]


def _entries_after_plan(
    existing: list[ExistingWikiEntry],
    plans: list[WikiDocumentPlan],
) -> list[ExistingWikiEntry]:
    """원본 하나의 문서 계획을 다음 원본이 볼 현재 Page 목록에 반영한다."""
    merged = {entry.document_key: entry for entry in existing}
    for plan in plans:
        merged[plan.document_key] = ExistingWikiEntry(
            document_kind=plan.document_kind,
            document_key=plan.document_key,
            title=plan.title,
            domain=plan.domain,
            summary=plan.summary,
            metadata=plan.metadata,
        )
    return list(merged.values())


def _relations_for_next_source(
    relations: list[WikiRelationPlan],
) -> list[WikiRelationPlan]:
    """이전 원본의 현재 관측 표식을 제거해 다음 원본으로 오귀속하지 않는다."""
    return [
        replace(
            relation,
            metadata={
                key: value
                for key, value in relation.metadata.items()
                if key != "observed_in_current_build"
            },
        )
        for relation in relations
    ]


def _combine_persisted(results: list[PersistedWikiBuild]) -> PersistedWikiBuild:
    """원본별 저장 결과를 최종 현재 문서가 한 번씩 포함된 결과로 합친다."""
    if not results:
        raise ValueError("V3 전체 재구성 저장 결과가 없습니다.")
    documents = {
        document.document_id: document
        for result in results
        for document in result.affected_documents
    }
    latest = results[-1]
    return replace(
        latest,
        affected_documents=list(documents.values()),
        superseded_relation_count=sum(
            result.superseded_relation_count for result in results
        ),
    )


def _affected_document_payload(persisted: PersistedWikiBuild) -> list[dict[str, object]]:
    """저장 문서를 Job 결과에 넣을 원문 없는 식별·상태 Payload로 만든다."""
    return [
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
    ]


def build_wiki_full_rebuild_graph_v3() -> Any:
    """원본별 내부 단계를 노드로 드러낸 V3 전체 재구성 그래프를 컴파일한다."""

    async def load_manifest(
        state: WikiFullRebuildState,
        runtime: Runtime[WikiFullRebuildRuntimeContext],
    ) -> dict[str, object]:
        """활성 원본과 온보딩 해석 의존성을 짧은 조회 Transaction에서 고정한다."""
        connection = runtime.context.connection
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=state["user_id"])
            sources = await list_user_source_versions_for_rebuild(
                connection,
                user_id=state["user_id"],
            )
            has_custom_keywords = any(
                source.source_type == "onboarding_seed"
                and isinstance(
                    source.source_metadata.get("custom_labels"),
                    list,
                )
                and bool(source.source_metadata.get("custom_labels"))
                for source in sources
            )
            resolution_existing_entries: list[ExistingWikiEntry] = []
            if has_custom_keywords:
                resolution_existing_entries = [
                    *await list_existing_wiki_entries(
                        connection,
                        user_id=state["user_id"],
                        document_kind="entity",
                    ),
                    *await list_existing_wiki_entries(
                        connection,
                        user_id=state["user_id"],
                        document_kind="concept",
                    ),
                ]
            dependencies: dict[str, tuple[list[Any], list[Any]]] = {}
            for source in sources:
                if source.source_type != "onboarding_seed":
                    continue
                metadata = source.source_metadata
                taxonomy_version = str(
                    metadata.get("interest_taxonomy_version") or ""
                ).strip()
                raw_custom_labels = metadata.get("custom_labels", [])
                custom_labels = (
                    [str(item) for item in raw_custom_labels]
                    if isinstance(raw_custom_labels, list)
                    else []
                )
                taxonomy_contexts = (
                    await list_onboarding_topic_contexts(
                        connection,
                        taxonomy_version=taxonomy_version,
                        locale="ko-KR",
                    )
                    if taxonomy_version
                    else []
                )
                cached_contexts = await list_cached_custom_topic_contexts(
                    connection,
                    user_id=state["user_id"],
                    keywords=custom_labels,
                    locale=str(metadata.get("preferred_language") or "ko"),
                )
                dependencies[source.source_document_version_id] = (
                    taxonomy_contexts,
                    cached_contexts,
                )
        return {
            "sources": sources,
            "source_index": 0,
            "resolution_existing_entries": resolution_existing_entries,
            "onboarding_dependencies": dependencies,
            "generated_custom_contexts": [],
            "existing_entities": [],
            "existing_concepts": [],
            "existing_relations": [],
            "onboarding_anchors": [],
            "staged": [],
        }

    def route_manifest(state: WikiFullRebuildState) -> str:
        """활성 원본 유무에 따라 순차 재구성 또는 retire 경로를 선택한다."""
        return "process" if state.get("sources") else "retire"

    async def select_source(state: WikiFullRebuildState) -> dict[str, object]:
        """고정 manifest에서 다음 원본을 선택하고 원본별 임시 상태를 초기화한다."""
        source = state["sources"][state["source_index"]]
        if source.raw_content is None:
            raise ValueError(
                "전체 재구성 원본에 Markdown 본문이 없습니다: "
                f"{source.source_document_version_id}"
            )
        return {
            "current_source": source,
            "onboarding_contexts": [],
            "onboarding_context_model": None,
            "identity_resolution": None,
            "relation_candidates": {},
            "relation_model": "deterministic:onboarding-anchor-v1",
        }

    async def resolve_onboarding_context(
        state: WikiFullRebuildState,
    ) -> dict[str, object]:
        """온보딩 원본이면 taxonomy·캐시·기존 Page·LLM 순서로 Topic을 해석한다."""
        source = state["current_source"]
        if source.source_type != "onboarding_seed":
            return {
                "onboarding_contexts": [],
                "onboarding_context_model": None,
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
        taxonomy_contexts, cached_contexts = state[
            "onboarding_dependencies"
        ].get(source.source_document_version_id, ([], []))
        resolution = await to_thread(
            resolve_onboarding_contexts,
            selected_topic_ids=selected_topic_ids,
            custom_keywords=custom_labels,
            taxonomy_version=(
                str(metadata.get("interest_taxonomy_version") or "").strip()
                or None
            ),
            locale=str(metadata.get("preferred_language") or "ko"),
            taxonomy_contexts=taxonomy_contexts,
            cached_contexts=cached_contexts,
            existing_entries=state["resolution_existing_entries"],
            model=state["model"],
        )
        contexts = [
            replace(context, matched_existing_key=None)
            for context in resolution.contexts
        ]
        return {
            "onboarding_contexts": contexts,
            "onboarding_context_model": resolution.model_trace,
            "generated_custom_contexts": [
                *state["generated_custom_contexts"],
                *resolution.generated_contexts,
            ],
        }

    async def classify_source(
        state: WikiFullRebuildState,
        runtime: Runtime[WikiFullRebuildRuntimeContext],
    ) -> dict[str, object]:
        """현재 원본에서 새 Entity·Concept 후보를 추출하고 모델 표식을 남긴다."""
        source = state["current_source"]
        classification, model_trace = await to_thread(
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
            classifier=runtime.context.classifier,
            onboarding_contexts=state["onboarding_contexts"],
        )
        return {
            "classification": classification,
            "classification_model": model_trace,
        }

    async def prepare_identity(state: WikiFullRebuildState) -> dict[str, object]:
        """표면형으로 확정 가능한 중복을 병합하고 의미 충돌만 분리한다."""
        draft = prepare_wiki_identity_resolution(
            classification=state["classification"],
            existing_entities=state["existing_entities"],
            existing_concepts=state["existing_concepts"],
        )
        return {"resolution_draft": draft}

    def route_identity(state: WikiFullRebuildState) -> str:
        """모호한 identity가 있을 때만 LLM 판정 노드로 보낸다."""
        return "resolve" if state["resolution_draft"].conflicts else "validate"

    async def resolve_identity(state: WikiFullRebuildState) -> dict[str, object]:
        """남은 identity 충돌을 한 번의 의미 판정으로 해소한다."""
        result = await to_thread(
            resolve_wiki_identity_conflicts,
            draft=state["resolution_draft"],
            source_title=state["current_source"].title,
            model=state["model"],
        )
        return {"identity_resolution": result}

    async def validate_identity(state: WikiFullRebuildState) -> dict[str, object]:
        """canonical 중복과 잘못된 기존 Key를 검사해 분류를 확정한다."""
        resolution = state.get("identity_resolution")
        classification = (
            resolution.classification
            if resolution is not None
            else state["resolution_draft"].classification
        )
        validated = validate_wiki_identity_quality(
            classification=classification,
            existing_entities=state["existing_entities"],
            existing_concepts=state["existing_concepts"],
        )
        return {
            "classification": validated,
            "identity_model": (
                resolution.model
                if resolution is not None
                else "deterministic:wiki-surface-v1"
            ),
        }

    async def recall_relations(state: WikiFullRebuildState) -> dict[str, object]:
        """현재 분류 노드별 기존 Page·온보딩 anchor 관계 후보를 제한해 찾는다."""
        if state["current_source"].source_type == "onboarding_seed":
            return {"relation_candidates": {}}
        candidates = build_relation_candidate_sets(
            classification=state["classification"],
            existing_entries=[
                *state["existing_entities"],
                *state["existing_concepts"],
            ],
            existing_relations=state["existing_relations"],
            onboarding_anchor_ids=state["onboarding_anchors"],
        )
        return {"relation_candidates": candidates}

    async def link_relations(
        state: WikiFullRebuildState,
        runtime: Runtime[WikiFullRebuildRuntimeContext],
    ) -> dict[str, object]:
        """후보 전체를 검토해 근거·confidence가 있는 관계를 확정한다."""
        source = state["current_source"]
        if source.source_type == "onboarding_seed":
            return {"relation_model": "deterministic:onboarding-anchor-v1"}
        linked = await to_thread(
            runtime.context.linker,
            source_title=source.title,
            source_content=source.raw_content,
            classification=state["classification"],
            candidates_by_node=state["relation_candidates"],
            model=state["model"],
        )
        return {
            "classification": linked,
            "relation_model": state["model"],
        }

    async def plan_source(state: WikiFullRebuildState) -> dict[str, object]:
        """현재 원본의 분류를 문서·관계·Schema·Artifact 계획으로 변환한다."""
        source = state["current_source"]
        context_trace = (
            f";context={state['onboarding_context_model']}"
            if state.get("onboarding_context_model")
            else ""
        )
        plan = build_wiki_plan(
            source_title=source.title,
            source_url=source.canonical_url,
            source_tags=source.tags,
            source_content_hash=source.content_hash,
            source_size_bytes=len(source.raw_content.encode("utf-8")),
            classification=state["classification"],
            existing_entities=state["existing_entities"],
            existing_concepts=state["existing_concepts"],
            generated_at=state["generated_at"],
            model=(
                f"{state['classification_model']}{context_trace};"
                f"identity={state['identity_model']};"
                f"relation={state['relation_model']};rebuild=langgraph_v3"
            ),
            existing_relations=state["existing_relations"],
        )
        return {"current_plan": plan}

    async def accumulate_source(state: WikiFullRebuildState) -> dict[str, object]:
        """현재 원본 계획을 메모리 Snapshot에 반영하고 다음 원본 위치로 이동한다."""
        source = state["current_source"]
        plan = state["current_plan"]
        anchors = list(state["onboarding_anchors"])
        if source.source_type == "onboarding_seed":
            anchors.extend(
                [
                    *(
                        WikiNodeIdentity("entity", document.document_key)
                        for document in plan.entities
                    ),
                    *(
                        WikiNodeIdentity("concept", document.document_key)
                        for document in plan.concepts
                    ),
                ]
            )
        return {
            "staged": [*state["staged"], (source, plan)],
            "existing_entities": _entries_after_plan(
                state["existing_entities"],
                plan.entities,
            ),
            "existing_concepts": _entries_after_plan(
                state["existing_concepts"],
                plan.concepts,
            ),
            "existing_relations": _relations_for_next_source(plan.relations),
            "onboarding_anchors": anchors,
            "source_index": state["source_index"] + 1,
        }

    def route_next_source(state: WikiFullRebuildState) -> str:
        """남은 원본이 있으면 순회하고 모두 처리했으면 전역 품질 Gate로 간다."""
        return (
            "next"
            if state["source_index"] < len(state["sources"])
            else "quality"
        )

    async def validate_snapshot(state: WikiFullRebuildState) -> dict[str, object]:
        """전체 원본 계획을 합친 최종 Snapshot의 구조·관계 품질을 검사한다."""
        quality = validate_wiki_quality(
            [*state["existing_entities"], *state["existing_concepts"]],
            state["existing_relations"],
        )
        if not quality.passed:
            errors = [
                issue.message
                for issue in quality.issues
                if issue.severity == "error"
            ]
            raise ValueError(
                "V3 전체 재구성 품질 게이트 실패: " + "; ".join(errors[:5])
            )
        return {"quality": quality}

    async def atomic_persist(
        state: WikiFullRebuildState,
        runtime: Runtime[WikiFullRebuildRuntimeContext],
    ) -> dict[str, object]:
        """검증 계획 전체를 한 Transaction에서 기존 Snapshot과 원자 교체한다."""
        connection = runtime.context.connection
        results: list[PersistedWikiBuild] = []
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=state["user_id"])
            await save_custom_topic_contexts(
                connection,
                user_id=state["user_id"],
                contexts=state["generated_custom_contexts"],
            )
            superseded_count = await supersede_personal_wiki_for_rebuild(
                connection,
                user_id=state["user_id"],
                job_id=state["job_id"],
            )
            for source, plan in state["staged"]:
                results.append(
                    await persist_wiki_build(
                        connection,
                        source=source,
                        plan=plan,
                        job_id=state["job_id"],
                    )
                )
            persisted = _combine_persisted(results)
            await update_full_wiki_rebuild_summary(
                connection,
                user_id=state["user_id"],
                wiki_version_id=persisted.wiki_version_id,
                source_count=len(state["sources"]),
                affected_document_count=len(persisted.affected_documents),
                superseded_document_count=superseded_count,
                quality_metrics=state["quality"].metrics,
            )
        return {
            "persisted": persisted,
            "superseded_document_count": superseded_count,
        }

    async def embed(
        state: WikiFullRebuildState,
        runtime: Runtime[WikiFullRebuildRuntimeContext],
    ) -> dict[str, object]:
        """교체된 Entity·Concept의 변경 Chunk를 현재 Embedding 모델로 갱신한다."""
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
                runtime.context.connection,
                namespace_key=f"user/{state['user_id']}",
                document_version_ids=version_ids,
                model=state["embedding_model"],
                job_id=state["job_id"],
                batch_threshold=state["embedding_batch_threshold"],
            )
            return {"embedding_count": count, "embedding_warning": None}
        except Exception as error:  # noqa: BLE001 - Wiki 교체는 이미 완료됨
            logger.warning("V3 전체 재구성 재임베딩 실패: %s", error)
            return {"embedding_count": 0, "embedding_warning": str(error)}

    async def retire_without_sources(
        state: WikiFullRebuildState,
        runtime: Runtime[WikiFullRebuildRuntimeContext],
    ) -> dict[str, object]:
        """활성 원본이 없으면 문서·관계·검색 Chunk·관심사 파생물을 비활성화한다."""
        connection = runtime.context.connection
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=state["user_id"])
            retired = await retire_personal_wiki_without_sources(
                connection,
                user_id=state["user_id"],
                job_id=state["job_id"],
            )
        return {
            "retirement_result": retired,
            "quality": validate_wiki_quality([], []),
            "embedding_count": 0,
            "embedding_warning": None,
            "superseded_document_count": retired["superseded_document_count"],
        }

    async def finalize(state: WikiFullRebuildState) -> dict[str, object]:
        """전체 재구성 또는 무원본 retire 결과를 공통 Job Payload로 확정한다."""
        quality = state["quality"]
        retirement = state.get("retirement_result")
        persisted = state.get("persisted")
        result: dict[str, object] = {
            "full_rebuild": True,
            "full_rebuild_pipeline_version": LANGGRAPH_FULL_REBUILD_VERSION,
            "source_count": len(state.get("sources", [])),
            "superseded_document_count": state.get(
                "superseded_document_count",
                0,
            ),
            "embedding_count": state.get("embedding_count", 0),
            "embedding_warning": state.get("embedding_warning"),
            "quality": {
                "metrics": dict(quality.metrics),
                "warnings": [
                    issue.message
                    for issue in quality.issues
                    if issue.severity == "warning"
                ],
            },
        }
        if persisted is not None:
            result.update(
                {
                    "wiki_version_id": persisted.wiki_version_id,
                    "wiki_version": persisted.wiki_version,
                    "chunk_count": persisted.chunk_count,
                    "stored_relation_count": persisted.stored_relation_count,
                    "affected_documents": _affected_document_payload(persisted),
                }
            )
        else:
            result.update(
                {
                    "wiki_version_id": None,
                    "wiki_version": None,
                    "chunk_count": 0,
                    "stored_relation_count": 0,
                    "affected_documents": [],
                    "unsearchable_chunk_count": (
                        retirement["unsearchable_chunk_count"]
                        if retirement is not None
                        else 0
                    ),
                }
            )
        return {"result": result}

    graph = StateGraph(
        WikiFullRebuildState,
        context_schema=WikiFullRebuildRuntimeContext,
    )
    graph.add_node("load_manifest", load_manifest)
    graph.add_node("select_source", select_source)
    graph.add_node("resolve_onboarding_context", resolve_onboarding_context)
    graph.add_node("classify_source", classify_source)
    graph.add_node("prepare_identity", prepare_identity)
    graph.add_node("resolve_identity", resolve_identity)
    graph.add_node("validate_identity", validate_identity)
    graph.add_node("recall_relations", recall_relations)
    graph.add_node("link_relations", link_relations)
    graph.add_node("plan_source", plan_source)
    graph.add_node("accumulate_source", accumulate_source)
    graph.add_node("validate_snapshot", validate_snapshot)
    graph.add_node("atomic_persist", atomic_persist)
    graph.add_node("embed", embed)
    graph.add_node("retire_without_sources", retire_without_sources)
    graph.add_node("finalize", finalize)
    graph.set_entry_point("load_manifest")
    graph.add_conditional_edges(
        "load_manifest",
        route_manifest,
        {"process": "select_source", "retire": "retire_without_sources"},
    )
    graph.add_edge("select_source", "resolve_onboarding_context")
    graph.add_edge("resolve_onboarding_context", "classify_source")
    graph.add_edge("classify_source", "prepare_identity")
    graph.add_conditional_edges(
        "prepare_identity",
        route_identity,
        {"resolve": "resolve_identity", "validate": "validate_identity"},
    )
    graph.add_edge("resolve_identity", "validate_identity")
    graph.add_edge("validate_identity", "recall_relations")
    graph.add_edge("recall_relations", "link_relations")
    graph.add_edge("link_relations", "plan_source")
    graph.add_edge("plan_source", "accumulate_source")
    graph.add_conditional_edges(
        "accumulate_source",
        route_next_source,
        {"next": "select_source", "quality": "validate_snapshot"},
    )
    graph.add_edge("validate_snapshot", "atomic_persist")
    graph.add_edge("atomic_persist", "embed")
    graph.add_edge("embed", "finalize")
    graph.add_edge("retire_without_sources", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


async def run_wiki_full_rebuild_graph_v3(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
    model: str = "gpt-4.1-mini",
    embedding_model: str = "text-embedding-3-small",
    embedding_batch_threshold: int = 0,
    classifier: WikiClassifier = classify_source_for_wiki,
    linker: WikiRelationLinker = link_wiki_relations,
    generated_at: str | None = None,
) -> dict[str, object]:
    """V3 내부 재구성 그래프를 실행하고 유지 루프가 합칠 Job 결과를 반환한다."""
    if not user_id or not job_id:
        raise ValueError("V3 전체 재구성에 user_id와 job_id가 필요합니다.")
    graph = build_wiki_full_rebuild_graph_v3()
    final = await graph.ainvoke(
        {
            "user_id": user_id,
            "job_id": job_id,
            "model": model,
            "embedding_model": embedding_model,
            "embedding_batch_threshold": embedding_batch_threshold,
            "generated_at": generated_at or datetime.now(UTC).isoformat(),
        },
        context=WikiFullRebuildRuntimeContext(
            connection=connection,
            classifier=classifier,
            linker=linker,
        ),
    )
    result = final.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("V3 전체 재구성 그래프가 Job 결과를 반환하지 않았습니다.")
    return dict(result)


__all__ = [
    "LANGGRAPH_FULL_REBUILD_VERSION",
    "WikiFullRebuildRuntimeContext",
    "WikiFullRebuildState",
    "build_wiki_full_rebuild_graph_v3",
    "run_wiki_full_rebuild_graph_v3",
]
