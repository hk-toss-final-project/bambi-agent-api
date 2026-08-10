"""개인 Wiki 노드 추출 후 기존 Wiki와의 관계를 별도 판정한다.

신규·갱신 노드와 하이브리드 검색이 선별한 기존 노드를 한 번의
LLM 검토에 넣고, 관계 유형·원문 근거·출처·신뢰도와 노드별
merge/connect/standalone 처리를 검증한다.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from agent.llm.api import complete, strip_json_fence
from agent.wiki_builder.features.relation_candidates import (
    RelationCandidateQuery,
    WikiGraphEdge,
    WikiNodeIdentity,
    WikiRelationCandidate,
    retrieve_wiki_relation_candidates,
)
from agent.wiki_builder.features.relations import parse_relation_candidates
from shared.wiki_models import (
    WikiClassification,
    ExistingWikiEntry,
    WikiNodeDisposition,
    WikiRelationClassification,
    WikiRelationPlan,
)

type WikiCompletion = Callable[..., str]

RELATION_LINKER_PROMPT_VERSION = "personal-wiki-relation-linker-v1"
_PROMPT_PATH = (
    Path(__file__).parents[2]
    / "prompts"
    / "templates"
    / "personal_wiki_relation_linker.md"
)
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()
_MIN_CONFIDENCE = {
    "source_explicit": 0.70,
    "semantic_inference": 0.78,
    "user_declared": 0.90,
    "system_rule": 0.90,
}


def build_relation_candidate_sets(
    *,
    classification: WikiClassification,
    existing_entries: Sequence[ExistingWikiEntry],
    existing_relations: Sequence[WikiRelationPlan] = (),
    onboarding_anchor_ids: Sequence[WikiNodeIdentity] = (),
    query_embeddings: Mapping[str, Sequence[float]] | None = None,
    candidate_embeddings: Mapping[WikiNodeIdentity, Sequence[float]] | None = None,
) -> dict[str, list[WikiRelationCandidate]]:
    """추출 노드별로 어휘·Vector·Graph·온보딩 후보를 Top-K로 만든다.

    Embedding은 호출자가 제공한 경우에만 후보 신호로 쓰이며, 이 함수는
    검색 점수로 관계를 생성하지 않는다.
    """
    graph_edges = [
        WikiGraphEdge(
            source=WikiNodeIdentity(
                relation.source_document_kind,
                relation.source_document_key,
            ),
            target=WikiNodeIdentity(
                relation.target_document_kind,
                relation.target_document_key,
            ),
            relation_type=relation.relation_type,
            weight=float(relation.metadata.get("confidence", 1.0)),
        )
        for relation in existing_relations
        if str(relation.metadata.get("status") or "active") == "active"
        and str(relation.metadata.get("review_status") or "accepted") == "accepted"
    ]
    embeddings = candidate_embeddings or {}
    queries = query_embeddings or {}
    result: dict[str, list[WikiRelationCandidate]] = {}
    index = 1
    for entity in classification.entities:
        reference = f"N{index}"
        matched = (
            WikiNodeIdentity("entity", entity.matched_existing_key)
            if entity.matched_existing_key
            else None
        )
        vector = queries.get(reference)
        result[reference] = retrieve_wiki_relation_candidates(
            RelationCandidateQuery(
                label=entity.name,
                aliases=tuple(entity.aliases),
                context=entity.description,
                matched_existing_identity=matched,
                embedding=tuple(vector) if vector is not None else None,
            ),
            existing_entries,
            graph_edges=graph_edges,
            onboarding_anchor_ids=onboarding_anchor_ids,
            candidate_embeddings=embeddings,
        )
        index += 1
    for concept in classification.concepts:
        reference = f"N{index}"
        matched = (
            WikiNodeIdentity("concept", concept.matched_existing_key)
            if concept.matched_existing_key
            else None
        )
        vector = queries.get(reference)
        result[reference] = retrieve_wiki_relation_candidates(
            RelationCandidateQuery(
                label=concept.title,
                aliases=tuple(concept.aliases),
                context=concept.definition,
                matched_existing_identity=matched,
                embedding=tuple(vector) if vector is not None else None,
            ),
            existing_entries,
            graph_edges=graph_edges,
            onboarding_anchor_ids=onboarding_anchor_ids,
            candidate_embeddings=embeddings,
        )
        index += 1
    return result


def _incoming_refs(
    classification: WikiClassification,
) -> tuple[dict[str, tuple[str, str, str | None]], list[str]]:
    """신규·갱신 노드에 안정적인 참조를 부여하고 프롬프트 문장을 만든다."""
    refs: dict[str, tuple[str, str, str | None]] = {}
    lines: list[str] = []
    index = 1
    for entity in classification.entities:
        reference = f"N{index}"
        refs[reference] = ("entity", entity.name, entity.matched_existing_key)
        lines.append(
            f"- {reference}: entity / {entity.name} / subtype={entity.subtype} / "
            f"matched={entity.matched_existing_key or '-'} / "
            f"aliases={entity.aliases} / {entity.description or '(설명 없음)'}"
        )
        index += 1
    for concept in classification.concepts:
        reference = f"N{index}"
        refs[reference] = ("concept", concept.title, concept.matched_existing_key)
        lines.append(
            f"- {reference}: concept / {concept.title} / subtype={concept.subtype} / "
            f"matched={concept.matched_existing_key or '-'} / "
            f"aliases={concept.aliases} / {concept.definition or '(정의 없음)'}"
        )
        index += 1
    return refs, lines


def _candidate_refs(
    candidates_by_node: Mapping[str, Sequence[WikiRelationCandidate]],
    *,
    start_index: int,
) -> tuple[dict[str, tuple[str, str, str | None]], list[str]]:
    """후보 세트의 중복 노드를 하나로 합치고 검색 신호를 프롬프트에 남긴다."""
    merged: dict[tuple[str, str], tuple[WikiRelationCandidate, set[str]]] = {}
    for incoming_ref, candidates in candidates_by_node.items():
        for candidate in candidates:
            identity = (
                candidate.entry.document_kind,
                candidate.entry.document_key,
            )
            if identity not in merged:
                merged[identity] = (candidate, {incoming_ref})
            else:
                merged[identity][1].add(incoming_ref)
    refs: dict[str, tuple[str, str, str | None]] = {}
    lines: list[str] = []
    for offset, (_identity, (candidate, incoming_refs)) in enumerate(
        sorted(merged.items()), start=start_index
    ):
        reference = f"X{offset}"
        entry = candidate.entry
        refs[reference] = (entry.document_kind, entry.title, entry.document_key)
        signal_text = ", ".join(
            f"{signal.kind}:{signal.score:.3f}" for signal in candidate.signals
        )
        lines.append(
            f"- {reference}: {entry.document_kind} / key={entry.document_key} / "
            f"title={entry.title} / subtype={entry.domain or 'other'} / "
            f"summary={entry.summary or '(없음)'} / score={candidate.score:.3f} / "
            f"signals=[{signal_text}] / for={sorted(incoming_refs)}"
        )
    return refs, lines


def _deduplicate_relations(
    relations: Sequence[WikiRelationClassification],
) -> list[WikiRelationClassification]:
    """같은 방향·유형의 관계 중 신뢰도가 높은 하나만 남긴다."""
    merged: dict[tuple[str, str, str, str, str], WikiRelationClassification] = {}
    for relation in relations:
        signature = (
            relation.source_kind,
            (relation.source_matched_key or relation.source_name).casefold(),
            relation.target_kind,
            (relation.target_matched_key or relation.target_name).casefold(),
            relation.relation_type,
        )
        current = merged.get(signature)
        if current is None or relation.confidence > current.confidence:
            merged[signature] = relation
    return list(merged.values())


def _accepted_relations(
    relations: Sequence[WikiRelationClassification],
    *,
    incoming_refs: set[str],
    ref_by_identity: Mapping[tuple[str, str], str],
) -> tuple[list[WikiRelationClassification], list[str]]:
    """검토 상태·provenance별 최소 신뢰도·신규 노드 포함 조건을 검사한다."""
    accepted: list[WikiRelationClassification] = []
    warnings: list[str] = []
    for relation in relations:
        source_identity = (
            relation.source_kind,
            (relation.source_matched_key or relation.source_name).casefold(),
        )
        target_identity = (
            relation.target_kind,
            (relation.target_matched_key or relation.target_name).casefold(),
        )
        endpoint_refs = {
            ref_by_identity.get(source_identity),
            ref_by_identity.get(target_identity),
        }
        if not endpoint_refs.intersection(incoming_refs):
            warnings.append("신규·갱신 노드가 없는 기존 관계를 제외했습니다.")
            continue
        minimum = _MIN_CONFIDENCE.get(relation.provenance_kind, 1.0)
        if relation.review_status != "accepted":
            warnings.append(
                f"{relation.source_name}->{relation.target_name} 관계가 accepted 상태가 아니어 제외됐습니다."
            )
            continue
        if relation.confidence < minimum:
            warnings.append(
                f"{relation.source_name}->{relation.target_name} 관계 신뢰도 "
                f"{relation.confidence:.2f}가 기준 {minimum:.2f}보다 낮아 제외됐습니다."
            )
            continue
        if relation.provenance_kind == "semantic_inference" and not relation.rationale:
            warnings.append(
                f"{relation.source_name}->{relation.target_name} 의미 관계에 rationale가 없어 제외됐습니다."
            )
            continue
        accepted.append(relation)
    return _deduplicate_relations(accepted), warnings


def _parse_dispositions(
    raw: object,
    *,
    incoming_refs: Mapping[str, tuple[str, str, str | None]],
    relations: Sequence[WikiRelationClassification],
) -> tuple[list[WikiNodeDisposition], list[str]]:
    """LLM disposition을 검증하고 누락된 노드를 결정적 기본값으로 보완한다."""
    warnings: list[str] = []
    raw_by_ref: dict[str, dict[str, object]] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            reference = str(item.get("node_ref") or "").strip()
            if reference in incoming_refs and reference not in raw_by_ref:
                raw_by_ref[reference] = item
    connected = {
        (
            relation.source_kind,
            (relation.source_matched_key or relation.source_name).casefold(),
        )
        for relation in relations
    } | {
        (
            relation.target_kind,
            (relation.target_matched_key or relation.target_name).casefold(),
        )
        for relation in relations
    }
    dispositions: list[WikiNodeDisposition] = []
    for reference, (kind, name, matched_key) in incoming_refs.items():
        item = raw_by_ref.get(reference)
        expected = (
            "merge"
            if matched_key
            else "connect"
            if (kind, (matched_key or name).casefold()) in connected
            else "standalone"
        )
        supplied = str(item.get("disposition") or "") if item else ""
        disposition = supplied if supplied in {"merge", "connect", "standalone"} else expected
        if disposition != expected:
            warnings.append(
                f"{reference} disposition {disposition}을 검증 결과 {expected}로 교정했습니다."
            )
            disposition = expected
        reason = str(item.get("reason") or "").strip() if item else ""
        if not reason:
            reason = {
                "merge": "canonical identity가 기존 Wiki 노드와 일치",
                "connect": "품질 게이트를 통과한 관계가 있음",
                "standalone": "검증된 관계를 확정하지 못함",
            }[disposition]
        dispositions.append(
            WikiNodeDisposition(
                node_name=name,
                node_kind=kind,
                disposition=disposition,
                reason=reason,
                matched_existing_key=matched_key,
            )
        )
    return dispositions, warnings


def link_wiki_relations(
    *,
    source_title: str,
    source_content: str,
    classification: WikiClassification,
    candidates_by_node: Mapping[str, Sequence[WikiRelationCandidate]],
    model: str,
    completion: WikiCompletion = complete,
) -> WikiClassification:
    """추출 노드 전체와 Top-K 기존 후보를 한 번 검토해 관계를 확정한다."""
    incoming, incoming_lines = _incoming_refs(classification)
    if not incoming:
        return classification
    candidate_refs, candidate_lines = _candidate_refs(
        candidates_by_node, start_index=1
    )
    all_refs = {**incoming, **candidate_refs}
    user_prompt = (
        f"[원본 제목]\n{source_title}\n\n"
        f"[신규/갱신 노드]\n{chr(10).join(incoming_lines)}\n\n"
        f"[기존 Wiki 후보]\n{chr(10).join(candidate_lines) or '(없음)'}\n\n"
        f"[원본 본문]\n{source_content}"
    )
    try:
        raw_response = completion(_SYSTEM_PROMPT, user_prompt, model=model)
        payload = json.loads(strip_json_fence(raw_response))
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        dispositions, _warnings = _parse_dispositions(
            None, incoming_refs=incoming, relations=[]
        )
        return replace(
            classification,
            relations=[],
            node_dispositions=dispositions,
            relation_warnings=[
                *classification.relation_warnings,
                f"관계 판정 응답을 검증하지 못했습니다: {error}",
            ],
        )
    if not isinstance(payload, dict):
        payload = {}
    parsed = parse_relation_candidates(
        payload.get("relations"),
        node_refs=all_refs,
        source_content=source_content,
        model=model,
        prompt_version=RELATION_LINKER_PROMPT_VERSION,
    )
    ref_by_identity = {
        (kind, (matched_key or name).casefold()): reference
        for reference, (kind, name, matched_key) in all_refs.items()
    }
    accepted, quality_warnings = _accepted_relations(
        parsed.relations,
        incoming_refs=set(incoming),
        ref_by_identity=ref_by_identity,
    )
    dispositions, disposition_warnings = _parse_dispositions(
        payload.get("dispositions"),
        incoming_refs=incoming,
        relations=accepted,
    )
    return replace(
        classification,
        relations=accepted,
        node_dispositions=dispositions,
        relation_warnings=list(
            dict.fromkeys(
                [
                    *classification.relation_warnings,
                    *parsed.warnings,
                    *quality_warnings,
                    *disposition_warnings,
                ]
            )
        ),
    )
