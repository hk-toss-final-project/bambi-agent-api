"""개인 Wiki 관계 후보를 원문 근거와 노드 참조 기준으로 검증한다.

LLM이 반환한 관계의 출발·도착 노드를 이미 분류된 entity·concept로 제한하고
관계 유형·자기 참조·중복·원문 인용을 검증한다. 노드가 여러 개인데 유효한
관계가 없으면 같은 원문을 대상으로 관계만 한 번 재검토한다.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from agent.llm.api import strip_json_fence
from shared.wiki_models import (
    ConceptClassification,
    EntityClassification,
    WikiRelationClassification,
)

type WikiCompletion = Callable[..., str]
type WikiNodeRef = tuple[str, str, str | None]

_PROMPT_PATH = (
    Path(__file__).parents[2]
    / "prompts"
    / "templates"
    / "personal_wiki_relation_reviewer.md"
)
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()
_ALLOWED_RELATIONS = {
    ("entity", "entity"): "entity_relation",
    ("entity", "concept"): "applies_concept",
    ("concept", "concept"): "related_concept",
}


@dataclass(frozen=True, slots=True)
class RelationReviewResult:
    """관계 재검토에서 검증된 관계와 경고를 함께 반환한다."""

    relations: list[WikiRelationClassification]
    warnings: list[str]


def _normalized_ref(value: object) -> str:
    """LLM 노드 참조를 대소문자와 주변 공백에 무관한 키로 정규화한다."""
    return str(value or "").strip().casefold()


def _evidence_exists(evidence: str, source_content: str) -> bool:
    """줄바꿈·연속 공백 차이를 허용해 근거가 원문에 있는지 확인한다."""
    if evidence in source_content:
        return True
    normalized_evidence = " ".join(evidence.split())
    normalized_source = " ".join(source_content.split())
    return bool(normalized_evidence) and normalized_evidence in normalized_source


def parse_relation_candidates(
    raw_relations: object,
    *,
    node_refs: dict[str, WikiNodeRef],
    source_content: str | None,
) -> RelationReviewResult:
    """LLM 관계 배열을 검증된 개인 Wiki 관계 후보로 변환한다."""
    if raw_relations is None:
        return RelationReviewResult(relations=[], warnings=[])
    if not isinstance(raw_relations, list):
        return RelationReviewResult(
            relations=[], warnings=["relations가 JSON 배열이 아닙니다."]
        )

    normalized_refs = {
        _normalized_ref(reference): node for reference, node in node_refs.items()
    }
    relations: list[WikiRelationClassification] = []
    warnings: list[str] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for index, raw in enumerate(raw_relations, start=1):
        if not isinstance(raw, dict):
            warnings.append(f"relations[{index}]가 JSON 객체가 아닙니다.")
            continue
        source_ref = _normalized_ref(raw.get("source_ref"))
        target_ref = _normalized_ref(raw.get("target_ref"))
        source = normalized_refs.get(source_ref)
        target = normalized_refs.get(target_ref)
        if source is None or target is None:
            warnings.append(
                f"relations[{index}]가 존재하지 않는 노드를 참조합니다: "
                f"{raw.get('source_ref')} -> {raw.get('target_ref')}"
            )
            continue
        source_kind, source_name, source_matched_key = source
        target_kind, target_name, target_matched_key = target
        source_identity = source_matched_key or source_name
        target_identity = target_matched_key or target_name
        if (
            source_kind == target_kind
            and source_identity.casefold() == target_identity.casefold()
        ):
            warnings.append(f"relations[{index}]의 자기 참조를 제외했습니다.")
            continue
        relation_type = str(raw.get("relation_type") or "").strip()
        expected_type = _ALLOWED_RELATIONS.get((source_kind, target_kind))
        if expected_type is None or relation_type != expected_type:
            warnings.append(
                f"relations[{index}]의 노드 종류와 관계 유형이 일치하지 않습니다: "
                f"{source_kind}->{target_kind}/{relation_type or '(없음)'}"
            )
            continue
        evidence = str(raw.get("evidence") or "").strip()
        if not evidence:
            warnings.append(f"relations[{index}]에 원문 근거가 없습니다.")
            continue
        if source_content is not None and not _evidence_exists(evidence, source_content):
            warnings.append(f"relations[{index}]의 근거가 원문에 존재하지 않습니다.")
            continue
        signature = (
            source_kind,
            source_identity.casefold(),
            target_kind,
            target_identity.casefold(),
            relation_type,
        )
        if signature in seen:
            continue
        seen.add(signature)
        relations.append(
            WikiRelationClassification(
                source_name=source_name,
                source_kind=source_kind,
                target_name=target_name,
                target_kind=target_kind,
                relation_type=relation_type,
                evidence=evidence,
                source_matched_key=source_matched_key,
                target_matched_key=target_matched_key,
            )
        )
    return RelationReviewResult(relations=relations, warnings=warnings)


def _review_candidates(
    entities: Sequence[EntityClassification],
    concepts: Sequence[ConceptClassification],
) -> tuple[dict[str, WikiNodeRef], str]:
    """관계 재검토용 안정적인 참조와 노드 설명을 만든다."""
    refs: dict[str, WikiNodeRef] = {}
    lines: list[str] = []
    for index, entity in enumerate(entities, start=1):
        reference = f"E{index}"
        refs[reference] = ("entity", entity.name, entity.matched_existing_key)
        lines.append(
            f"- {reference}: entity / {entity.name} / {entity.subtype} / "
            f"{entity.description or '(설명 없음)'}"
        )
    for index, concept in enumerate(concepts, start=1):
        reference = f"C{index}"
        refs[reference] = ("concept", concept.title, concept.matched_existing_key)
        lines.append(
            f"- {reference}: concept / {concept.title} / {concept.subtype} / "
            f"{concept.definition or '(정의 없음)'}"
        )
    return refs, "\n".join(lines)


def review_missing_relations(
    *,
    source_content: str,
    entities: Sequence[EntityClassification],
    concepts: Sequence[ConceptClassification],
    model: str,
    completion: WikiCompletion,
) -> RelationReviewResult:
    """확정된 노드 사이의 원문 기반 관계를 LLM으로 한 번 재검토한다."""
    node_refs, candidate_text = _review_candidates(entities, concepts)
    if len(node_refs) < 2:
        return RelationReviewResult(relations=[], warnings=[])
    user_prompt = (
        f"[확정 노드]\n{candidate_text}\n\n"
        f"[원본 본문]\n{source_content}"
    )
    raw_response = completion(_SYSTEM_PROMPT, user_prompt, model=model)
    try:
        payload = json.loads(strip_json_fence(raw_response))
    except json.JSONDecodeError as error:
        return RelationReviewResult(
            relations=[],
            warnings=[f"관계 재검토 응답이 JSON 형식이 아닙니다: {error}"],
        )
    if not isinstance(payload, dict):
        return RelationReviewResult(
            relations=[], warnings=["관계 재검토 응답이 JSON 객체가 아닙니다."]
        )
    reviewed = parse_relation_candidates(
        payload.get("relations"),
        node_refs=node_refs,
        source_content=source_content,
    )
    if reviewed.relations:
        return reviewed
    return RelationReviewResult(
        relations=[],
        warnings=[
            *reviewed.warnings,
            "노드가 2개 이상이지만 원문에서 검증된 관계를 찾지 못했습니다.",
        ],
    )
