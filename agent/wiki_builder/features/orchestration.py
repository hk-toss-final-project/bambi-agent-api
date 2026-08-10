"""개인 Wiki 증분 Build 오케스트레이션.

원본·기존 Wiki 조회, 분류, Build 계획, DB 영속화를 WBA-001 한 건의
실행 경계로 묶는다. 일반 원본의 LLM 호출 동안은 DB Transaction을 열어 두지 않는다.
"""

from asyncio import to_thread
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import logging
from typing import Any

from psycopg import AsyncConnection

from agent.wiki_builder.features.classification import (
    classify_source_for_wiki,
    classify_wiki_source,
)
from agent.wiki_builder.features.identity_resolution import (
    prepare_wiki_identity_resolution,
    resolve_wiki_identity_conflicts,
    validate_wiki_identity_quality,
)
from agent.wiki_builder.features.planning import build_wiki_plan
from agent.wiki_builder.features.onboarding_contexts import resolve_onboarding_contexts
from agent.wiki_builder.features.quality import WikiQualityReport, wba_014
from agent.wiki_builder.features.embeddings import (
    generate_relation_query_embeddings,
    wba_011,
)
from agent.wiki_builder.features.relation_candidates import WikiNodeIdentity
from agent.wiki_builder.features.relation_linking import (
    build_relation_candidate_sets,
    link_wiki_relations,
)
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
    get_user_source_document_version_for_agent,
    list_existing_wiki_entries,
    list_existing_wiki_relations,
    list_cached_custom_topic_contexts,
    list_onboarding_topic_contexts,
    list_onboarding_wiki_anchor_keys,
    list_wiki_node_embeddings,
    list_user_source_versions_for_rebuild,
    persist_wiki_build,
    save_custom_topic_contexts,
    set_personal_wiki_scope,
    supersede_personal_wiki_for_rebuild,
    update_full_wiki_rebuild_summary,
)

type DictRow = dict[str, Any]
type WikiClassifier = Callable[..., WikiClassification]
type WikiBuildRunner = Callable[..., Awaitable[dict[str, object]]]
type WikiRelationLinker = Callable[..., WikiClassification]

logger = logging.getLogger("agent.wiki_builder")


@dataclass(frozen=True, slots=True)
class FullWikiRebuildResult:
    """전체 원본을 재처리해 활성화한 Wiki 재구성 결과."""

    persisted: PersistedWikiBuild
    source_count: int
    quality: WikiQualityReport
    embedding_count: int
    superseded_document_count: int


async def build_incremental_wiki(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_document_version_id: str,
    job_id: str,
    model: str = "gpt-4.1-mini",
    classifier: WikiClassifier = classify_source_for_wiki,
    generated_at: str | None = None,
) -> tuple[PersistedWikiBuild, WikiBuildPlan]:
    """저장된 클리핑 Version 하나를 증분 개인 Wiki Build로 처리한다.

    조회 Transaction을 닫은 뒤 원본 유형에 맞게 분류하고, 결과를 별도
    Transaction에서 문서·Version·출처·관계·Chunk·Snapshot으로 저장한다.
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
        if not source.raw_content:
            raise ValueError(
                f"DB에 Markdown 원문이 없습니다: {source_document_version_id}"
            )
        existing_entities = await list_existing_wiki_entries(
            connection, user_id=user_id, document_kind="entity"
        )
        existing_concepts = await list_existing_wiki_entries(
            connection, user_id=user_id, document_kind="concept"
        )
        existing_relations = await list_existing_wiki_relations(
            connection,
            namespace_key=source.namespace_key,
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
        cached_contexts = []
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
            if taxonomy_version:
                taxonomy_contexts = await list_onboarding_topic_contexts(
                    connection,
                    taxonomy_version=taxonomy_version,
                    locale="ko-KR",
                )
            cached_contexts = await list_cached_custom_topic_contexts(
                connection,
                user_id=user_id,
                keywords=custom_labels,
                locale=str(source.source_metadata.get("preferred_language") or "ko"),
            )

    onboarding_contexts = []
    generated_custom_contexts = []
    onboarding_context_model: str | None = None
    if source.source_type == "onboarding_seed":
        raw_topic_ids = source.source_metadata.get("selected_topic_ids", [])
        raw_custom_labels = source.source_metadata.get("custom_labels", [])
        resolution = await to_thread(
            resolve_onboarding_contexts,
            selected_topic_ids=(
                [str(item) for item in raw_topic_ids]
                if isinstance(raw_topic_ids, list)
                else []
            ),
            custom_keywords=(
                [str(item) for item in raw_custom_labels]
                if isinstance(raw_custom_labels, list)
                else []
            ),
            taxonomy_version=(
                str(
                    source.source_metadata.get("interest_taxonomy_version") or ""
                ).strip()
                or None
            ),
            locale=str(source.source_metadata.get("preferred_language") or "ko"),
            taxonomy_contexts=taxonomy_contexts,
            cached_contexts=cached_contexts,
            existing_entries=[*existing_entities, *existing_concepts],
            model=model,
        )
        onboarding_contexts = list(resolution.contexts)
        generated_custom_contexts = list(resolution.generated_contexts)
        onboarding_context_model = resolution.model_trace
    classification, classification_model = await to_thread(
        classify_wiki_source,
        source_type=source.source_type,
        source_metadata=source.source_metadata,
        source_title=source.title,
        source_content=source.raw_content,
        source_description=source.description,
        source_tags=source.tags,
        existing_entities=existing_entities,
        existing_concepts=existing_concepts,
        model=model,
        classifier=classifier,
        onboarding_contexts=onboarding_contexts,
    )
    resolution_draft = prepare_wiki_identity_resolution(
        classification=classification,
        existing_entities=existing_entities,
        existing_concepts=existing_concepts,
    )
    identity_resolution = await to_thread(
        resolve_wiki_identity_conflicts,
        draft=resolution_draft,
        source_title=source.title,
        model=model,
    )
    classification = validate_wiki_identity_quality(
        classification=identity_resolution.classification,
        existing_entities=existing_entities,
        existing_concepts=existing_concepts,
    )
    relation_model = "deterministic:onboarding-anchor-v1"
    if source.source_type != "onboarding_seed":
        candidate_vectors = {
            WikiNodeIdentity(item.document_kind, item.document_key): item.embedding
            for item in node_embeddings
        }
        query_texts = [
            f"{entity.name}\n{entity.description}".strip()
            for entity in classification.entities
        ] + [
            f"{concept.title}\n{concept.definition}".strip()
            for concept in classification.concepts
        ]
        query_vectors: dict[str, tuple[float, ...]] = {}
        if query_texts and candidate_vectors:
            try:
                embedded = await to_thread(
                    generate_relation_query_embeddings,
                    query_texts,
                    model="text-embedding-3-small",
                )
                query_vectors = {
                    f"N{index}": vector
                    for index, vector in enumerate(embedded, start=1)
                }
            except Exception as error:  # noqa: BLE001 - 비Vector 폴백 보존
                logger.warning("Wiki 관계 Query Embedding 실패: %s", error)
        candidates = build_relation_candidate_sets(
            classification=classification,
            existing_entries=[*existing_entities, *existing_concepts],
            existing_relations=existing_relations,
            onboarding_anchor_ids=[
                WikiNodeIdentity(kind, key) for kind, key in onboarding_anchor_keys
            ],
            query_embeddings=query_vectors,
            candidate_embeddings=candidate_vectors,
        )
        classification = await to_thread(
            link_wiki_relations,
            source_title=source.title,
            source_content=source.raw_content,
            classification=classification,
            candidates_by_node=candidates,
            model=model,
        )
        relation_model = model
    timestamp = generated_at or datetime.now(UTC).isoformat()
    classification_trace = classification_model
    if onboarding_contexts:
        classification_trace = (
            f"{classification_trace};context={onboarding_context_model}"
        )
    plan = build_wiki_plan(
        source_title=source.title,
        source_url=source.canonical_url,
        source_tags=source.tags,
        source_content_hash=source.content_hash,
        source_size_bytes=len(source.raw_content.encode("utf-8")),
        classification=classification,
        existing_entities=existing_entities,
        existing_concepts=existing_concepts,
        generated_at=timestamp,
        model=(
            f"{classification_trace};identity={identity_resolution.model};"
            f"relation={relation_model}"
        ),
        existing_relations=existing_relations,
    )
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        await save_custom_topic_contexts(
            connection,
            user_id=user_id,
            contexts=generated_custom_contexts,
        )
        persisted = await persist_wiki_build(
            connection,
            source=source,
            plan=plan,
            job_id=job_id,
        )
    changed_version_ids = [
        document.document_version_id
        for document in persisted.affected_documents
        if document.document_kind in {"entity", "concept"}
        and document.action in {"create", "created", "update", "updated"}
    ]
    if changed_version_ids:
        try:
            await wba_011(
                connection,
                namespace_key=source.namespace_key,
                document_version_ids=changed_version_ids,
                model="text-embedding-3-small",
            )
        except Exception as error:  # noqa: BLE001 - 저장된 Build는 성공으로 유지
            logger.warning("Wiki 재임베딩 실패: %s", error)
    return persisted, plan


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wba_001(
    runner: WikiBuildRunner,
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_document_version_id: str,
    job_id: str,
    model: str = "gpt-4.1-mini",
) -> dict[str, object]:
    """[WBA-001] Incremental Wiki Build.

    새로 추가된 사용자 데이터만 개인 Wiki에 반영한다.
    """
    if not user_id:
        raise ValueError("WBA-001에 user_id가 필요합니다.")
    if not source_document_version_id:
        raise ValueError("WBA-001에 source_document_version_id가 필요합니다.")
    if not job_id:
        raise ValueError("WBA-001에 job_id가 필요합니다.")
    if not model:
        raise ValueError("WBA-001의 model은 빈 문자열이면 안 됩니다.")
    return await runner(
        connection,
        user_id=user_id,
        source_document_version_id=source_document_version_id,
        job_id=job_id,
        model=model,
    )


def _entries_after_plan(
    existing: list[ExistingWikiEntry],
    plans: list[WikiDocumentPlan],
) -> list[ExistingWikiEntry]:
    """메모리 재구성 상태에 이번 문서 계획을 upsert한다."""
    merged = {(entry.document_kind, entry.document_key): entry for entry in existing}
    for plan in plans:
        merged[(plan.document_kind, plan.document_key)] = ExistingWikiEntry(
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
    """이전 원본 관계의 '현재 Build 관측' 표식을 제거해 근거 오귀속을 막는다."""
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


def _combine_rebuild_results(
    results: list[PersistedWikiBuild],
) -> PersistedWikiBuild:
    """원본별 저장 결과를 최종 현재 문서만 담은 Full Rebuild 결과로 합친다."""
    if not results:
        raise ValueError("Full Wiki Rebuild 저장 결과가 없습니다.")
    final_documents = {
        document.document_id: document
        for result in results
        for document in result.affected_documents
    }
    latest = results[-1]
    return replace(
        latest,
        affected_documents=list(final_documents.values()),
        superseded_relation_count=sum(
            result.superseded_relation_count for result in results
        ),
    )


async def rebuild_full_wiki(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
    model: str = "gpt-4.1-mini",
    classifier: WikiClassifier = classify_source_for_wiki,
    linker: WikiRelationLinker = link_wiki_relations,
    generated_at: str | None = None,
) -> FullWikiRebuildResult:
    """사용자 원본 전체를 메모리에서 재분류한 뒤 Wiki를 원자적으로 교체한다.

    LLM 호출·identity·관계 Linker·Lint는 기존 Wiki를 변경하지 않고 먼저
    완료한다. 모든 계획이 통과한 뒤에만 하나의 DB Transaction에서 기존
    파생 Wiki를 supersede하고 새 Snapshot을 저장하므로, 중간 실패는 기존
    활성 Wiki를 손상시키지 않는다.
    """
    if not user_id or not job_id:
        raise ValueError("WBA-002에 user_id와 job_id가 필요합니다.")
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        sources = await list_user_source_versions_for_rebuild(
            connection, user_id=user_id
        )
        has_custom_keywords = any(
            source.source_type == "onboarding_seed"
            and isinstance(source.source_metadata.get("custom_labels"), list)
            and bool(source.source_metadata.get("custom_labels"))
            for source in sources
        )
        resolution_existing_entries = []
        if has_custom_keywords:
            resolution_existing_entries = [
                *(
                    await list_existing_wiki_entries(
                        connection, user_id=user_id, document_kind="entity"
                    )
                ),
                *(
                    await list_existing_wiki_entries(
                        connection, user_id=user_id, document_kind="concept"
                    )
                ),
            ]
        onboarding_dependencies: dict[str, tuple[list, list]] = {}
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
            preferred_language = str(metadata.get("preferred_language") or "ko")
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
                user_id=user_id,
                keywords=custom_labels,
                locale=preferred_language,
            )
            onboarding_dependencies[source.source_document_version_id] = (
                taxonomy_contexts,
                cached_contexts,
            )
    if not sources:
        raise ValueError("전체 Wiki를 재구성할 활성 원본이 없습니다.")

    existing_entities: list[ExistingWikiEntry] = []
    existing_concepts: list[ExistingWikiEntry] = []
    existing_relations: list[WikiRelationPlan] = []
    onboarding_anchors: list[WikiNodeIdentity] = []
    staged: list[tuple[UserSourceDocumentForAgent, WikiBuildPlan]] = []
    generated_custom_contexts = []
    timestamp = generated_at or datetime.now(UTC).isoformat()

    for source in sources:
        onboarding_contexts = []
        onboarding_context_model: str | None = None
        if source.source_type == "onboarding_seed":
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
            taxonomy_contexts, cached_contexts = onboarding_dependencies.get(
                source.source_document_version_id, ([], [])
            )
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
                existing_entries=resolution_existing_entries,
                model=model,
            )
            # 기존 Wiki는 바로 뒤 Transaction에서 전부 supersede된다. 설명은
            # 재사용하되, 곧 사라질 Head key로 병합하도록 지시하지 않는다.
            onboarding_contexts = [
                replace(context, matched_existing_key=None)
                for context in resolution.contexts
            ]
            generated_custom_contexts.extend(resolution.generated_contexts)
            onboarding_context_model = resolution.model_trace
        classification, classification_model = await to_thread(
            classify_wiki_source,
            source_type=source.source_type,
            source_metadata=source.source_metadata,
            source_title=source.title,
            source_content=source.raw_content,
            source_description=source.description,
            source_tags=source.tags,
            existing_entities=existing_entities,
            existing_concepts=existing_concepts,
            model=model,
            classifier=classifier,
            onboarding_contexts=onboarding_contexts,
        )
        draft = prepare_wiki_identity_resolution(
            classification=classification,
            existing_entities=existing_entities,
            existing_concepts=existing_concepts,
        )
        identity = await to_thread(
            resolve_wiki_identity_conflicts,
            draft=draft,
            source_title=source.title,
            model=model,
        )
        classification = validate_wiki_identity_quality(
            classification=identity.classification,
            existing_entities=existing_entities,
            existing_concepts=existing_concepts,
        )
        relation_model = "deterministic:onboarding-anchor-v1"
        if source.source_type != "onboarding_seed":
            candidates = build_relation_candidate_sets(
                classification=classification,
                existing_entries=[*existing_entities, *existing_concepts],
                existing_relations=existing_relations,
                onboarding_anchor_ids=onboarding_anchors,
            )
            classification = await to_thread(
                linker,
                source_title=source.title,
                source_content=source.raw_content,
                classification=classification,
                candidates_by_node=candidates,
                model=model,
            )
            relation_model = model
        plan = build_wiki_plan(
            source_title=source.title,
            source_url=source.canonical_url,
            source_tags=source.tags,
            source_content_hash=source.content_hash,
            source_size_bytes=len(source.raw_content.encode("utf-8")),
            classification=classification,
            existing_entities=existing_entities,
            existing_concepts=existing_concepts,
            generated_at=timestamp,
            model=(
                f"{classification_model}"
                f"{';context=' + onboarding_context_model if onboarding_context_model else ''};"
                f"identity={identity.model};"
                f"relation={relation_model};rebuild=v1"
            ),
            existing_relations=existing_relations,
        )
        staged.append((source, plan))
        existing_entities = _entries_after_plan(existing_entities, plan.entities)
        existing_concepts = _entries_after_plan(existing_concepts, plan.concepts)
        existing_relations = _relations_for_next_source(plan.relations)
        if source.source_type == "onboarding_seed":
            onboarding_anchors.extend(
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

    quality = await wba_014(
        [*existing_entities, *existing_concepts], existing_relations
    )
    if not quality.passed:
        errors = [issue.message for issue in quality.issues if issue.severity == "error"]
        raise ValueError("Full Wiki Rebuild 품질 게이트 실패: " + "; ".join(errors[:5]))

    persisted_results: list[PersistedWikiBuild] = []
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        await save_custom_topic_contexts(
            connection,
            user_id=user_id,
            contexts=generated_custom_contexts,
        )
        superseded_count = await supersede_personal_wiki_for_rebuild(
            connection, user_id=user_id, job_id=job_id
        )
        for source, plan in staged:
            persisted_results.append(
                await persist_wiki_build(
                    connection,
                    source=source,
                    plan=plan,
                    job_id=job_id,
                )
            )
        affected_document_count = len(
            {
                document.document_id
                for result in persisted_results
                for document in result.affected_documents
            }
        )
        await update_full_wiki_rebuild_summary(
            connection,
            user_id=user_id,
            wiki_version_id=persisted_results[-1].wiki_version_id,
            source_count=len(sources),
            affected_document_count=affected_document_count,
            superseded_document_count=superseded_count,
        )

    persisted = _combine_rebuild_results(persisted_results)
    version_ids = [
        document.document_version_id
        for document in persisted.affected_documents
        if document.document_kind in {"entity", "concept"}
        and document.action in {"create", "created", "update", "updated"}
    ]
    embedding_count = 0
    if version_ids:
        try:
            embedding_count = await wba_011(
                connection,
                namespace_key=f"user/{user_id}",
                document_version_ids=version_ids,
                model="text-embedding-3-small",
            )
        except Exception as error:  # noqa: BLE001 - Wiki 교체는 이미 완료
            logger.warning("Full Wiki Rebuild 재임베딩 실패: %s", error)
    return FullWikiRebuildResult(
        persisted=persisted,
        source_count=len(sources),
        quality=quality,
        embedding_count=embedding_count,
        superseded_document_count=superseded_count,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wba_002(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
    model: str = "gpt-4.1-mini",
) -> FullWikiRebuildResult:
    """[WBA-002] Full Wiki Rebuild.

    전체 개인 Wiki를 재분류하고 재구성한다.
    """
    return await rebuild_full_wiki(
        connection,
        user_id=user_id,
        job_id=job_id,
        model=model,
    )
