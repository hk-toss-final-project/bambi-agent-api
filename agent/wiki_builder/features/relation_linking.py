"""개인 Wiki 노드 추출 후 기존 Wiki와의 관계를 별도 판정한다.

신규·갱신 노드와 하이브리드 검색이 선별한 기존 노드를 한 번의
LLM 검토에 넣고, 관계 유형·원문 근거·출처·신뢰도와 노드별
merge/connect/standalone 처리를 검증한다.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from agent.llm.api import complete, strip_json_fence
from agent.wiki_builder.features.identity_resolution import normalize_wiki_surface
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
type RelationIdentity = tuple[str, str]

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


@dataclass(frozen=True, slots=True)
class _CandidateReferenceSet:
    """프롬프트 후보 참조와 원래 신규 노드 범위·표면형을 함께 보존한다."""

    refs: dict[str, tuple[str, str, str | None]]
    lines: tuple[str, ...]
    incoming_refs_by_candidate: dict[str, frozenset[str]]
    surfaces_by_candidate: dict[str, tuple[str, ...]]


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


def _relation_identity(
    kind: str, name: str, matched_key: str | None
) -> RelationIdentity:
    """관계 endpoint를 canonical 문서 종류와 식별자 조합으로 정규화한다."""
    return kind, (matched_key or name).casefold()


def _metadata_aliases(entry: ExistingWikiEntry) -> tuple[str, ...]:
    """기존 Wiki 후보 Metadata에서 비어 있지 않은 문자열 별칭을 읽는다."""
    aliases = entry.metadata.get("aliases", ())
    if not isinstance(aliases, (list, tuple)):
        return ()
    return tuple(str(alias).strip() for alias in aliases if str(alias).strip())


def _unique_surfaces(values: Sequence[str]) -> tuple[str, ...]:
    """원래 순서를 유지하며 빈 값과 동일 canonical 표면형을 제거한다."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        surface = str(value).strip()
        marker = normalize_wiki_surface(surface)
        if surface and marker and marker not in seen:
            seen.add(marker)
            result.append(surface)
    return tuple(result)


def _candidate_refs(
    candidates_by_node: Mapping[str, Sequence[WikiRelationCandidate]],
    *,
    start_index: int,
    excluded_identities: Collection[RelationIdentity] = (),
) -> _CandidateReferenceSet:
    """후보 세트의 중복·신규 노드를 정리하고 검색 신호를 프롬프트에 남긴다."""
    excluded = set(excluded_identities)
    merged: dict[tuple[str, str], tuple[WikiRelationCandidate, set[str]]] = {}
    for incoming_ref, candidates in candidates_by_node.items():
        for candidate in candidates:
            identity = (
                candidate.entry.document_kind,
                candidate.entry.document_key.casefold(),
            )
            if identity in excluded:
                continue
            if identity not in merged:
                merged[identity] = (candidate, {incoming_ref})
            else:
                merged[identity][1].add(incoming_ref)
    refs: dict[str, tuple[str, str, str | None]] = {}
    lines: list[str] = []
    incoming_refs_by_candidate: dict[str, frozenset[str]] = {}
    surfaces_by_candidate: dict[str, tuple[str, ...]] = {}
    for offset, (_identity, (candidate, incoming_refs)) in enumerate(
        sorted(merged.items()), start=start_index
    ):
        reference = f"X{offset}"
        entry = candidate.entry
        refs[reference] = (entry.document_kind, entry.title, entry.document_key)
        incoming_refs_by_candidate[reference] = frozenset(incoming_refs)
        surfaces_by_candidate[reference] = _unique_surfaces(
            (entry.title, entry.document_key, *_metadata_aliases(entry))
        )
        signal_text = ", ".join(
            f"{signal.kind}:{signal.score:.3f}" for signal in candidate.signals
        )
        lines.append(
            f"- {reference}: {entry.document_kind} / key={entry.document_key} / "
            f"title={entry.title} / subtype={entry.domain or 'other'} / "
            f"summary={entry.summary or '(없음)'} / score={candidate.score:.3f} / "
            f"signals=[{signal_text}] / for={sorted(incoming_refs)}"
        )
    return _CandidateReferenceSet(
        refs=refs,
        lines=tuple(lines),
        incoming_refs_by_candidate=incoming_refs_by_candidate,
        surfaces_by_candidate=surfaces_by_candidate,
    )


def _surface_is_grounded(surfaces: Sequence[str], text: str) -> bool:
    """후보 제목·key·별칭 중 하나가 제목과 인용 근거에 명시됐는지 확인한다."""
    folded_text = unicodedata.normalize("NFKC", text).casefold()
    normalized_text = normalize_wiki_surface(text)
    for surface in surfaces:
        folded_surface = unicodedata.normalize("NFKC", surface).casefold().strip()
        marker = normalize_wiki_surface(surface)
        if not marker:
            continue
        if marker.isascii() and marker.isalnum() and len(marker) <= 3:
            if re.search(
                rf"(?<![a-z0-9]){re.escape(folded_surface)}(?![a-z0-9])",
                folded_text,
            ):
                return True
            continue
        if marker in normalized_text:
            return True
    return False


def _filter_relation_reference_scope(
    raw_relations: object,
    *,
    incoming_refs: Collection[str],
    candidates: _CandidateReferenceSet,
    source_title: str,
) -> tuple[object, list[str]]:
    """LLM 관계가 후보별 회수 범위와 source_explicit 표면 근거를 지키는지 검사한다."""
    if not isinstance(raw_relations, list):
        return raw_relations, []
    normalized_incoming = {reference.casefold() for reference in incoming_refs}
    candidate_scopes = {
        reference.casefold(): {item.casefold() for item in scopes}
        for reference, scopes in candidates.incoming_refs_by_candidate.items()
    }
    candidate_surfaces = {
        reference.casefold(): surfaces
        for reference, surfaces in candidates.surfaces_by_candidate.items()
    }
    filtered: list[object] = []
    warnings: list[str] = []
    for index, raw in enumerate(raw_relations, start=1):
        if not isinstance(raw, dict):
            filtered.append(raw)
            continue
        source_ref = str(raw.get("source_ref") or "").strip().casefold()
        target_ref = str(raw.get("target_ref") or "").strip().casefold()
        candidate_ref: str | None = None
        incoming_ref: str | None = None
        if source_ref in candidate_scopes and target_ref in normalized_incoming:
            candidate_ref, incoming_ref = source_ref, target_ref
        elif target_ref in candidate_scopes and source_ref in normalized_incoming:
            candidate_ref, incoming_ref = target_ref, source_ref
        if candidate_ref is None or incoming_ref is None:
            filtered.append(raw)
            continue
        if incoming_ref not in candidate_scopes[candidate_ref]:
            warnings.append(
                f"relations[{index}]의 기존 후보 {candidate_ref.upper()}는 "
                f"{incoming_ref.upper()}의 회수 후보가 아니어 제외했습니다."
            )
            continue
        provenance_kind = str(
            raw.get("provenance_kind") or "source_explicit"
        ).strip()
        if provenance_kind == "source_explicit":
            evidence = str(raw.get("evidence") or "").strip()
            grounding_text = f"{source_title}\n{evidence}"
            if not _surface_is_grounded(
                candidate_surfaces.get(candidate_ref, ()), grounding_text
            ):
                warnings.append(
                    f"relations[{index}]의 기존 후보 {candidate_ref.upper()}가 "
                    "원본 제목·evidence에 명시되지 않아 제외했습니다."
                )
                continue
        filtered.append(raw)
    return filtered, warnings


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
    incoming_identities: Collection[RelationIdentity],
) -> tuple[list[WikiRelationClassification], list[str]]:
    """검토 상태·provenance별 최소 신뢰도·신규 노드 포함 조건을 검사한다."""
    accepted: list[WikiRelationClassification] = []
    warnings: list[str] = []
    incoming_identity_set = set(incoming_identities)
    for relation in relations:
        source_identity = _relation_identity(
            relation.source_kind,
            relation.source_name,
            relation.source_matched_key,
        )
        target_identity = _relation_identity(
            relation.target_kind,
            relation.target_name,
            relation.target_matched_key,
        )
        if (
            source_identity not in incoming_identity_set
            and target_identity not in incoming_identity_set
        ):
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
    incoming_identities = {
        _relation_identity(kind, name, matched_key)
        for kind, name, matched_key in incoming.values()
    }
    candidate_references = _candidate_refs(
        candidates_by_node,
        start_index=1,
        excluded_identities=incoming_identities,
    )
    all_refs = {**incoming, **candidate_references.refs}
    user_prompt = (
        f"[원본 제목]\n{source_title}\n\n"
        f"[신규/갱신 노드]\n{chr(10).join(incoming_lines)}\n\n"
        f"[기존 Wiki 후보]\n{chr(10).join(candidate_references.lines) or '(없음)'}\n\n"
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
    scoped_relations, scope_warnings = _filter_relation_reference_scope(
        payload.get("relations"),
        incoming_refs=incoming,
        candidates=candidate_references,
        source_title=source_title,
    )
    parsed = parse_relation_candidates(
        scoped_relations,
        node_refs=all_refs,
        source_content=source_content,
        model=model,
        prompt_version=RELATION_LINKER_PROMPT_VERSION,
    )
    accepted, quality_warnings = _accepted_relations(
        parsed.relations,
        incoming_identities=incoming_identities,
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
                    *scope_warnings,
                    *parsed.warnings,
                    *quality_warnings,
                    *disposition_warnings,
                ]
            )
        ),
    )
