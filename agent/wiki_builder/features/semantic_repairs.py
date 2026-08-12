"""Personal Wiki V3 의미 감사 결과를 안전한 증분 수리 계획으로 변환한다.

검증된 누락 주제·관계를 기존 Wiki Planner 계약으로 변환하고, 모순·오래된
주장은 어느 한쪽을 지우지 않은 채 Page Metadata에 근거와 함께 보존한다.
모든 계획은 결정적 품질 Gate를 먼저 통과한 뒤 하나의 DB Transaction에서
저장하며 기존 원본 관계 support는 append 모드로 보존한다.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection

from agent.wiki_builder.models import (
    ConceptClassification,
    EntityClassification,
    ExistingWikiEntry,
    WikiBuildPlan,
    WikiClassification,
    WikiDocumentPlan,
    WikiRelationClassification,
    WikiRelationPlan,
)
from infrastructure.persistence.api import (
    PersistedWikiBuild,
    UserSourceDocumentForAgent,
    persist_wiki_build,
    set_personal_wiki_scope,
)

from .embeddings import wba_011
from .identity_resolution import normalize_wiki_surface
from .planning import build_wiki_plan
from .quality import (
    WikiQualityReport,
    is_wiki_relation_kind_pair_allowed,
    validate_wiki_quality,
)
from .semantic_audit import (
    WikiMissingRelationProposal,
    WikiMissingTopicProposal,
    WikiSemanticIssue,
    WikiSemanticIssueCode,
    WikiSemanticLintReport,
)
from .semantic_lint import (
    WikiSemanticLintContext,
    WikiSemanticPage,
    page_by_reference,
    source_by_reference,
)

type DictRow = dict[str, Any]
type WikiSemanticPersister = Callable[..., Awaitable[PersistedWikiBuild]]
type WikiSemanticEmbedder = Callable[..., Awaitable[int]]

logger = logging.getLogger("agent.wiki_builder")


@dataclass(frozen=True, slots=True)
class WikiSemanticRepairBatch:
    """하나의 활성 원본 Version을 근거로 저장할 결정적 분류 묶음."""

    source_document_version_id: str
    classification: WikiClassification
    issue_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WikiSemanticRepairPlan:
    """내부 수리 묶음과 쓰기 루프로 넘길 외부 지식 공백 계획."""

    batches: tuple[WikiSemanticRepairBatch, ...]
    research_issues: tuple[WikiSemanticIssue, ...]
    skipped_issue_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    metrics: Mapping[str, int | float]


@dataclass(frozen=True, slots=True)
class WikiSemanticStagedBatch:
    """원본과 저장 직전 Wiki Build 계획을 결합한 수리 한 묶음."""

    source: UserSourceDocumentForAgent
    plan: WikiBuildPlan
    issue_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WikiSemanticStaging:
    """원자 저장 전에 품질 Gate를 통과한 전체 수리 계획."""

    batches: tuple[WikiSemanticStagedBatch, ...]
    entries: tuple[ExistingWikiEntry, ...]
    relations: tuple[WikiRelationPlan, ...]
    quality: WikiQualityReport


@dataclass(frozen=True, slots=True)
class WikiSemanticRepairResult:
    """의미 수리 저장·Embedding 결과와 최종 구조 품질."""

    wiki_version_id: str | None
    repaired_issue_ids: tuple[str, ...]
    changed_document_version_ids: tuple[str, ...]
    affected_document_count: int
    stored_relation_count: int
    embedding_count: int
    quality: WikiQualityReport


@dataclass(slots=True)
class _TopicAccumulator:
    """같은 누락 주제 제안의 별칭·인용·문제 ID를 합친다."""

    proposal: WikiMissingTopicProposal
    issue_ids: set[str] = field(default_factory=set)
    aliases: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _BatchAccumulator:
    """한 원본 Version으로 반영할 Page·주제·관계를 누적한다."""

    entities: dict[str, EntityClassification] = field(default_factory=dict)
    concepts: dict[str, ConceptClassification] = field(default_factory=dict)
    topics: dict[tuple[str, str], _TopicAccumulator] = field(default_factory=dict)
    relations: dict[
        tuple[str, str, str, str, str], WikiRelationClassification
    ] = field(default_factory=dict)
    issue_ids: set[str] = field(default_factory=set)


@dataclass(slots=True)
class _PageRepairAccumulator:
    """기존 Page 하나에 추가할 모순·오래된 주장 Metadata를 누적한다."""

    page: WikiSemanticPage
    source_document_version_id: str
    issue_ids: set[str] = field(default_factory=set)
    contradictions: dict[str, dict[str, object]] = field(default_factory=dict)
    stale_claims: dict[str, dict[str, object]] = field(default_factory=dict)


def _metadata_strings(metadata: Mapping[str, object], key: str) -> tuple[str, ...]:
    """Metadata 배열에서 비어 있지 않은 문자열을 중복 없이 읽는다."""
    value = metadata.get(key)
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    return tuple(
        dict.fromkeys(
            normalized
            for item in value
            if (normalized := str(item).strip())
        )
    )


def _metadata_records(
    metadata: Mapping[str, object],
    key: str,
) -> dict[str, dict[str, object]]:
    """Metadata 객체 배열을 안정적인 ID Map으로 복원한다."""
    value = metadata.get(key)
    if isinstance(value, Mapping):
        items: Sequence[object] = (value,)
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        items = ()
    records: dict[str, dict[str, object]] = {}
    for index, raw in enumerate(items):
        if not isinstance(raw, Mapping):
            continue
        record = dict(raw)
        record_id = str(record.get("id") or f"legacy-{index}").strip()
        records.setdefault(record_id, record)
    return records


def _source_version_id(
    context: WikiSemanticLintContext,
    source_reference: str,
) -> str | None:
    """안정적인 Source 참조를 실제 활성 원본 Version ID로 변환한다."""
    source = source_by_reference(context).get(source_reference)
    return source.source_document_version_id if source is not None else None


def _primary_source_reference(issue: WikiSemanticIssue) -> str | None:
    """문제 수리에 사용할 첫 검증 근거 Source 참조를 선택한다."""
    if issue.relation is not None:
        return issue.relation.evidence_source_reference
    if issue.evidence:
        return issue.evidence[0].source_reference
    return issue.source_references[0] if issue.source_references else None


def _evidence_payload(
    issue: WikiSemanticIssue,
    context: WikiSemanticLintContext,
) -> list[dict[str, str]]:
    """문제 인용을 안정적인 실제 Source Version ID와 함께 직렬화한다."""
    payload: list[dict[str, str]] = []
    for evidence in issue.evidence:
        source_version_id = _source_version_id(
            context,
            evidence.source_reference,
        )
        if source_version_id is None:
            continue
        payload.append(
            {
                "source_document_version_id": source_version_id,
                "quote": evidence.quote,
            }
        )
    return payload


def _issue_record(
    issue: WikiSemanticIssue,
    context: WikiSemanticLintContext,
) -> dict[str, object]:
    """모순·오래된 주장을 삭제 없는 Page Metadata 항목으로 만든다."""
    return {
        "id": issue.issue_id,
        "severity": "warning",
        "semantic_severity": issue.severity,
        "message": issue.title,
        "rationale": issue.rationale,
        "confidence": issue.confidence,
        "evidence": _evidence_payload(issue, context),
    }


def _relation_signature(
    relation: WikiRelationClassification,
) -> tuple[str, str, str, str, str]:
    """분류 관계를 방향·endpoint·유형이 포함된 중복 제거 Key로 만든다."""
    return (
        relation.source_kind,
        relation.source_matched_key or normalize_wiki_surface(relation.source_name),
        relation.target_kind,
        relation.target_matched_key or normalize_wiki_surface(relation.target_name),
        relation.relation_type,
    )


def _proposal_relation(
    proposal: WikiMissingRelationProposal,
    *,
    context: WikiSemanticLintContext,
    report: WikiSemanticLintReport,
) -> WikiRelationClassification | None:
    """검증 누락 관계를 기존 Planner가 소비하는 분류 관계로 변환한다."""
    pages = page_by_reference(context)
    source_page = pages.get(proposal.source_page_reference)
    target_page = pages.get(proposal.target_page_reference)
    if source_page is None or target_page is None:
        return None
    if not is_wiki_relation_kind_pair_allowed(
        proposal.relation_type,
        source_page.document_kind,
        target_page.document_kind,
    ):
        return None
    return WikiRelationClassification(
        source_name=source_page.title,
        source_kind=source_page.document_kind,
        target_name=target_page.title,
        target_kind=target_page.document_kind,
        relation_type=proposal.relation_type,
        evidence=proposal.evidence,
        source_matched_key=source_page.document_key,
        target_matched_key=target_page.document_key,
        provenance_kind=proposal.provenance_kind,
        confidence=proposal.confidence,
        review_status="accepted",
        rationale=proposal.rationale,
        model=report.model,
        prompt_version=report.prompt_version,
    )


def _topic_relation(
    proposal: WikiMissingTopicProposal,
    *,
    issue: WikiSemanticIssue,
    context: WikiSemanticLintContext,
    report: WikiSemanticLintReport,
) -> WikiRelationClassification | None:
    """누락 주제와 기존 Page의 선택 관계를 Planner 분류 관계로 변환한다."""
    if proposal.related_page_reference is None:
        return None
    page = page_by_reference(context).get(proposal.related_page_reference)
    if page is None or proposal.relation_type is None:
        return None
    if proposal.relation_direction == "topic_to_page":
        source_name, source_kind, source_key = (
            proposal.title,
            proposal.document_kind,
            None,
        )
        target_name, target_kind, target_key = (
            page.title,
            page.document_kind,
            page.document_key,
        )
    else:
        source_name, source_kind, source_key = (
            page.title,
            page.document_kind,
            page.document_key,
        )
        target_name, target_kind, target_key = (
            proposal.title,
            proposal.document_kind,
            None,
        )
    if not is_wiki_relation_kind_pair_allowed(
        proposal.relation_type,
        source_kind,
        target_kind,
    ):
        return None
    evidence = issue.evidence[0].quote if issue.evidence else issue.rationale
    return WikiRelationClassification(
        source_name=source_name,
        source_kind=source_kind,
        target_name=target_name,
        target_kind=target_kind,
        relation_type=proposal.relation_type,
        evidence=evidence,
        source_matched_key=source_key,
        target_matched_key=target_key,
        provenance_kind="source_explicit",
        confidence=issue.confidence,
        review_status="accepted",
        rationale=issue.rationale,
        model=report.model,
        prompt_version=report.prompt_version,
    )


def _add_topic(
    batch: _BatchAccumulator,
    issue: WikiSemanticIssue,
) -> None:
    """누락 주제 한 건을 같은 원본 Batch의 정규화 주제 후보에 합친다."""
    proposal = issue.topic
    if proposal is None:
        return
    key = (proposal.document_kind, normalize_wiki_surface(proposal.title))
    topic = batch.topics.setdefault(key, _TopicAccumulator(proposal=proposal))
    topic.issue_ids.add(issue.issue_id)
    for alias in proposal.aliases:
        if alias not in topic.aliases:
            topic.aliases.append(alias)
    for evidence in issue.evidence:
        if evidence.quote not in topic.mentions:
            topic.mentions.append(evidence.quote)
    batch.issue_ids.add(issue.issue_id)


def _add_page_repairs(
    batches: dict[str, _BatchAccumulator],
    page_repairs: Mapping[tuple[str, str, str], _PageRepairAccumulator],
) -> None:
    """누적 Page Metadata 수리를 Entity·Concept 분류 후보로 변환한다."""
    for key in sorted(page_repairs):
        repair = page_repairs[key]
        page = repair.page
        metadata = dict(page.metadata)
        contradictions = _metadata_records(metadata, "contradictions")
        if not contradictions:
            contradictions = _metadata_records(metadata, "contradiction")
        contradictions.update(repair.contradictions)
        stale_claims = _metadata_records(metadata, "stale_claims")
        stale_claims.update(repair.stale_claims)
        issue_ids = tuple(
            dict.fromkeys(
                [
                    *_metadata_strings(metadata, "semantic_issue_ids"),
                    *sorted(repair.issue_ids),
                ]
            )
        )
        context_metadata: dict[str, object] = {
            "semantic_issue_ids": list(issue_ids),
            "semantic_maintenance_version": "langgraph_v3",
        }
        if contradictions:
            context_metadata["contradictions"] = list(contradictions.values())
        if stale_claims:
            context_metadata["stale_claims"] = list(stale_claims.values())
        batch = batches.setdefault(
            repair.source_document_version_id,
            _BatchAccumulator(),
        )
        batch.issue_ids.update(repair.issue_ids)
        subtype = str(metadata.get("subtype") or "other")
        if page.document_kind == "entity":
            batch.entities[page.document_key] = EntityClassification(
                name=page.title,
                subtype=subtype,
                matched_existing_key=page.document_key,
                role="mention",
                context_metadata=context_metadata,
            )
        else:
            batch.concepts[page.document_key] = ConceptClassification(
                title=page.title,
                subtype=subtype,
                matched_existing_key=page.document_key,
                overlaps_existing=True,
                role="mention",
                context_metadata=context_metadata,
            )


def _classification(batch: _BatchAccumulator) -> WikiClassification:
    """누적 Batch를 기존 Wiki Planner용 분류 값 객체로 확정한다."""
    entities = list(batch.entities.values())
    concepts = list(batch.concepts.values())
    for key in sorted(batch.topics):
        topic = batch.topics[key]
        proposal = topic.proposal
        context_metadata = {
            "semantic_issue_ids": sorted(topic.issue_ids),
            "semantic_maintenance_version": "langgraph_v3",
        }
        if proposal.document_kind == "entity":
            entities.append(
                EntityClassification(
                    name=proposal.title,
                    description=proposal.summary,
                    aliases=list(topic.aliases),
                    mentions=list(topic.mentions),
                    role="subject",
                    context_metadata=context_metadata,
                )
            )
        else:
            concepts.append(
                ConceptClassification(
                    title=proposal.title,
                    definition=proposal.summary,
                    aliases=list(topic.aliases),
                    mentions=list(topic.mentions),
                    role="subject",
                    context_metadata=context_metadata,
                )
            )
    return WikiClassification(
        source_summary="Wiki V3 의미 감사의 검증된 내부 수리",
        entities=entities,
        concepts=concepts,
        relations=list(batch.relations.values()),
    )


def plan_wiki_semantic_repairs(
    report: WikiSemanticLintReport,
    *,
    context: WikiSemanticLintContext,
) -> WikiSemanticRepairPlan:
    """검증 의미 문제를 내부 수리 Batch와 외부 조사 항목으로 분리한다."""
    batches: dict[str, _BatchAccumulator] = {}
    page_repairs: dict[tuple[str, str, str], _PageRepairAccumulator] = {}
    research_issues: list[WikiSemanticIssue] = []
    skipped: set[str] = set()
    warnings: list[str] = []
    pages = page_by_reference(context)

    for issue in report.issues:
        if issue.code is WikiSemanticIssueCode.KNOWLEDGE_GAP:
            research_issues.append(issue)
            continue
        source_reference = _primary_source_reference(issue)
        source_version_id = (
            _source_version_id(context, source_reference)
            if source_reference is not None
            else None
        )
        if source_version_id is None:
            skipped.add(issue.issue_id)
            warnings.append(f"{issue.issue_id}: 활성 근거 Source를 찾지 못했습니다.")
            continue
        batch = batches.setdefault(source_version_id, _BatchAccumulator())

        if issue.code is WikiSemanticIssueCode.MISSING_TOPIC:
            _add_topic(batch, issue)
            relation = (
                _topic_relation(
                    issue.topic,
                    issue=issue,
                    context=context,
                    report=report,
                )
                if issue.topic is not None
                else None
            )
            if issue.topic is not None and issue.topic.related_page_reference and relation is None:
                warnings.append(
                    f"{issue.issue_id}: 주제는 생성하지만 호환되지 않는 "
                    "선택 관계는 제외했습니다."
                )
            if relation is not None:
                batch.relations.setdefault(_relation_signature(relation), relation)
            continue

        if issue.code is WikiSemanticIssueCode.MISSING_RELATION:
            relation = (
                _proposal_relation(
                    issue.relation,
                    context=context,
                    report=report,
                )
                if issue.relation is not None
                else None
            )
            if relation is None:
                skipped.add(issue.issue_id)
                warnings.append(
                    f"{issue.issue_id}: 관계 유형과 endpoint 종류가 "
                    "호환되지 않습니다."
                )
                continue
            batch.relations.setdefault(_relation_signature(relation), relation)
            batch.issue_ids.add(issue.issue_id)
            continue

        if issue.code not in {
            WikiSemanticIssueCode.CONTRADICTION,
            WikiSemanticIssueCode.STALE_CLAIM,
        }:
            skipped.add(issue.issue_id)
            continue
        added = False
        for page_reference in issue.page_references:
            page = pages.get(page_reference)
            if page is None or issue.issue_id in _metadata_strings(
                page.metadata,
                "semantic_issue_ids",
            ):
                continue
            repair_key = (
                source_version_id,
                page.document_kind,
                page.document_key,
            )
            repair = page_repairs.setdefault(
                repair_key,
                _PageRepairAccumulator(
                    page=page,
                    source_document_version_id=source_version_id,
                ),
            )
            repair.issue_ids.add(issue.issue_id)
            record = _issue_record(issue, context)
            if issue.code is WikiSemanticIssueCode.CONTRADICTION:
                repair.contradictions[issue.issue_id] = record
            else:
                repair.stale_claims[issue.issue_id] = record
            added = True
        if not added:
            skipped.add(issue.issue_id)

    _add_page_repairs(batches, page_repairs)
    repair_batches = tuple(
        WikiSemanticRepairBatch(
            source_document_version_id=source_version_id,
            classification=_classification(batch),
            issue_ids=tuple(sorted(batch.issue_ids)),
        )
        for source_document_version_id, batch in sorted(batches.items())
        if batch.issue_ids
    )
    planned_issue_ids = {
        issue_id for batch in repair_batches for issue_id in batch.issue_ids
    }
    metrics: dict[str, int | float] = {
        "repair_batch_count": len(repair_batches),
        "planned_internal_issue_count": len(planned_issue_ids),
        "research_issue_count": len(research_issues),
        "skipped_issue_count": len(skipped),
    }
    return WikiSemanticRepairPlan(
        batches=repair_batches,
        research_issues=tuple(research_issues),
        skipped_issue_ids=tuple(sorted(skipped)),
        warnings=tuple(dict.fromkeys(warnings)),
        metrics=metrics,
    )


def _entries_after_plan(
    existing: Sequence[ExistingWikiEntry],
    plans: Sequence[WikiDocumentPlan],
) -> list[ExistingWikiEntry]:
    """기존 Page 목록에 한 수리 계획의 최신 문서 값을 반영한다."""
    merged = {
        (entry.document_kind, entry.document_key): entry for entry in existing
    }
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


def _relations_for_next_batch(
    relations: Sequence[WikiRelationPlan],
) -> list[WikiRelationPlan]:
    """다음 Batch가 이전 신규 관계를 재관측했다고 오인하지 않게 한다."""
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


def stage_wiki_semantic_repairs(
    repair_plan: WikiSemanticRepairPlan,
    *,
    sources: Sequence[UserSourceDocumentForAgent],
    entries: Sequence[ExistingWikiEntry],
    relations: Sequence[WikiRelationPlan],
    model: str,
    generated_at: str | None = None,
) -> WikiSemanticStaging:
    """내부 수리를 메모리에서 계획하고 최종 Snapshot 품질을 검증한다."""
    sources_by_version = {
        source.source_document_version_id: source for source in sources
    }
    current_entries = list(entries)
    current_relations = list(relations)
    staged: list[WikiSemanticStagedBatch] = []
    timestamp = generated_at or datetime.now(UTC).isoformat()
    for batch in repair_plan.batches:
        source = sources_by_version.get(batch.source_document_version_id)
        if source is None or source.raw_content is None:
            raise ValueError(
                "의미 수리 근거 원본 Version을 찾을 수 없습니다: "
                f"{batch.source_document_version_id}"
            )
        entities = [
            entry for entry in current_entries if entry.document_kind == "entity"
        ]
        concepts = [
            entry for entry in current_entries if entry.document_kind == "concept"
        ]
        wiki_plan = build_wiki_plan(
            source_title=source.title,
            source_url=source.canonical_url,
            source_tags=source.tags,
            source_content_hash=source.content_hash,
            source_size_bytes=len(source.raw_content.encode("utf-8")),
            classification=batch.classification,
            existing_entities=entities,
            existing_concepts=concepts,
            existing_relations=current_relations,
            generated_at=timestamp,
            model=f"{model};semantic-repair=langgraph_v3",
        )
        staged.append(
            WikiSemanticStagedBatch(
                source=source,
                plan=wiki_plan,
                issue_ids=batch.issue_ids,
            )
        )
        current_entries = _entries_after_plan(
            current_entries,
            [*wiki_plan.entities, *wiki_plan.concepts],
        )
        current_relations = _relations_for_next_batch(wiki_plan.relations)
    quality = validate_wiki_quality(current_entries, current_relations)
    if not quality.passed:
        errors = [
            issue.message for issue in quality.issues if issue.severity == "error"
        ]
        raise ValueError(
            "Wiki 의미 수리 품질 게이트 실패: " + "; ".join(errors[:5])
        )
    return WikiSemanticStaging(
        batches=tuple(staged),
        entries=tuple(current_entries),
        relations=tuple(current_relations),
        quality=quality,
    )


async def apply_wiki_semantic_repairs(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
    repair_plan: WikiSemanticRepairPlan,
    sources: Sequence[UserSourceDocumentForAgent],
    entries: Sequence[ExistingWikiEntry],
    relations: Sequence[WikiRelationPlan],
    model: str,
    embedding_model: str,
    embedding_batch_threshold: int = 0,
    generated_at: str | None = None,
    persister: WikiSemanticPersister = persist_wiki_build,
    embedder: WikiSemanticEmbedder = wba_011,
) -> WikiSemanticRepairResult:
    """검증된 의미 수리를 한 Transaction에 저장하고 변경 Page를 임베딩한다."""
    staging = stage_wiki_semantic_repairs(
        repair_plan,
        sources=sources,
        entries=entries,
        relations=relations,
        model=model,
        generated_at=generated_at,
    )
    if not staging.batches:
        return WikiSemanticRepairResult(
            wiki_version_id=None,
            repaired_issue_ids=(),
            changed_document_version_ids=(),
            affected_document_count=0,
            stored_relation_count=len(staging.relations),
            embedding_count=0,
            quality=staging.quality,
        )

    persisted: list[PersistedWikiBuild] = []
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        for batch in staging.batches:
            persisted.append(
                await persister(
                    connection,
                    source=batch.source,
                    plan=batch.plan,
                    job_id=job_id,
                    replace_source_relation_supports=False,
                )
            )

    affected_documents = {
        document.document_id: document
        for result in persisted
        for document in result.affected_documents
    }
    changed_version_ids = tuple(
        dict.fromkeys(
            document.document_version_id
            for document in affected_documents.values()
            if document.document_kind in {"entity", "concept"}
            and document.action in {"create", "created", "update", "updated"}
        )
    )
    embedding_count = 0
    if changed_version_ids:
        try:
            embedding_count = await embedder(
                connection,
                namespace_key=f"user/{user_id}",
                document_version_ids=changed_version_ids,
                model=embedding_model,
                job_id=job_id,
                batch_threshold=embedding_batch_threshold,
            )
        except Exception as error:  # noqa: BLE001 - 문서 수리는 이미 완료됨
            logger.warning("Wiki 의미 수리 재임베딩 실패: %s", error)
    return WikiSemanticRepairResult(
        wiki_version_id=persisted[-1].wiki_version_id,
        repaired_issue_ids=tuple(
            sorted(
                {
                    issue_id
                    for batch in staging.batches
                    for issue_id in batch.issue_ids
                }
            )
        ),
        changed_document_version_ids=changed_version_ids,
        affected_document_count=len(affected_documents),
        stored_relation_count=persisted[-1].stored_relation_count,
        embedding_count=embedding_count,
        quality=staging.quality,
    )


__all__ = [
    "WikiSemanticRepairBatch",
    "WikiSemanticRepairPlan",
    "WikiSemanticRepairResult",
    "WikiSemanticStagedBatch",
    "WikiSemanticStaging",
    "apply_wiki_semantic_repairs",
    "plan_wiki_semantic_repairs",
    "stage_wiki_semantic_repairs",
]
