"""개인 Wiki 노드의 표기 정규화와 기존 문서 후보 탐색.

띄어쓰기·구두점·대소문자 차이를 제거한 비교용 표면형을 만들고, 이번 Build의
분류 후보와 기존 entity·concept을 같은 의미 후보군으로 묶는다. 동일 kind의
대상이 하나로 확정되는 경우에는 코드로 병합하고, kind 충돌이나 복수 후보만
후속 의미 판정 단계에 넘긴다.
"""

from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from agent.llm.api import LlmCompletion, complete_with_usage, strip_json_fence

from shared.wiki_models import (
    ConceptClassification,
    EntityClassification,
    ExistingWikiEntry,
    WikiClassification,
)


@dataclass(frozen=True, slots=True)
class WikiIdentityOption:
    """의미 판정에서 선택할 수 있는 기존 Wiki 문서 한 건."""

    document_kind: str
    document_key: str
    title: str
    aliases: tuple[str, ...]
    domain: str | None
    summary: str | None


@dataclass(frozen=True, slots=True)
class WikiIdentityConflict:
    """코드만으로 하나의 canonical identity를 정할 수 없는 후보군."""

    conflict_id: str
    incoming_refs: tuple[str, ...]
    incoming_labels: tuple[str, ...]
    incoming_kinds: tuple[str, ...]
    options: tuple[WikiIdentityOption, ...]


@dataclass(frozen=True, slots=True)
class WikiResolutionDraft:
    """결정적으로 정리한 분류 결과와 남은 의미 충돌 목록."""

    classification: WikiClassification
    conflicts: tuple[WikiIdentityConflict, ...]


@dataclass(frozen=True, slots=True)
class WikiIdentityResolutionResult:
    """identity 충돌 판정이 끝난 분류 결과와 LLM 사용량."""

    classification: WikiClassification
    model: str
    resolved_conflict_count: int
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class _ResolutionDecision:
    """검증을 마친 conflict별 canonical identity 선택."""

    conflict_id: str
    action: str
    target_kind: str
    target_key: str | None
    canonical_label: str


@dataclass(frozen=True, slots=True)
class _IncomingNode:
    """분류 후보를 표면형 비교에 사용할 내부 노드로 표현한다."""

    ref: str
    document_kind: str
    label: str
    aliases: tuple[str, ...]
    value: EntityClassification | ConceptClassification


_PROMPT_PATH = (
    Path(__file__).parents[2]
    / "prompts"
    / "templates"
    / "personal_wiki_identity_resolver.md"
)
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()
_DETERMINISTIC_RESOLVER_MODEL = "deterministic:wiki-surface-v1"

type IdentityResolverCompletion = Callable[..., LlmCompletion]


def normalize_wiki_surface(value: str) -> str:
    """Unicode·대소문자·공백·구두점 차이를 제거한 비교 키를 만든다."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _unique(items: Iterable[str]) -> list[str]:
    """표기 순서를 유지하며 빈 값과 대소문자 중복을 제거한다."""
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = item.strip()
        marker = value.casefold()
        if value and marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def _metadata_aliases(entry: ExistingWikiEntry) -> tuple[str, ...]:
    """기존 문서 Metadata에서 문자열 별칭만 안전하게 읽는다."""
    aliases = entry.metadata.get("aliases", [])
    if not isinstance(aliases, list):
        return ()
    return tuple(_unique(str(item) for item in aliases))


def _incoming_nodes(classification: WikiClassification) -> list[_IncomingNode]:
    """분류 결과를 안정적인 참조 ID가 있는 내부 노드 목록으로 바꾼다."""
    nodes = [
        _IncomingNode(
            ref=f"entity:{index}",
            document_kind="entity",
            label=entity.name,
            aliases=tuple(entity.aliases),
            value=entity,
        )
        for index, entity in enumerate(classification.entities)
        if entity.name.strip()
    ]
    nodes.extend(
        _IncomingNode(
            ref=f"concept:{index}",
            document_kind="concept",
            label=concept.title,
            aliases=tuple(concept.aliases),
            value=concept,
        )
        for index, concept in enumerate(classification.concepts)
        if concept.title.strip()
    )
    return nodes


def _surfaces(label: str, aliases: Sequence[str]) -> set[str]:
    """이름과 별칭에서 비어 있지 않은 비교 표면형 집합을 만든다."""
    return {
        surface
        for item in (label, *aliases)
        if (surface := normalize_wiki_surface(item))
    }


def _merge_text(first: str, second: str) -> str:
    """두 설명을 내용 손실과 동일 문장 중복 없이 합친다."""
    if not first:
        return second
    if not second or second in first:
        return first
    if first in second:
        return second
    return f"{first}\n\n{second}"


def _merge_entities(
    nodes: Sequence[_IncomingNode], target: ExistingWikiEntry | None
) -> EntityClassification:
    """같은 대상으로 확정된 entity 분류 후보를 하나로 병합한다."""
    values = [node.value for node in nodes if isinstance(node.value, EntityClassification)]
    current = values[0]
    for incoming in values[1:]:
        current = replace(
            current,
            description=_merge_text(current.description, incoming.description),
            aliases=_unique(
                [
                    *current.aliases,
                    *(
                        [incoming.name]
                        if incoming.name.casefold() != current.name.casefold()
                        else []
                    ),
                    *incoming.aliases,
                ]
            ),
            related_entity_names=_unique(
                [*current.related_entity_names, *incoming.related_entity_names]
            ),
            related_concepts=_unique(
                [*current.related_concepts, *incoming.related_concepts]
            ),
            mentions=_unique([*current.mentions, *incoming.mentions]),
            is_alias=current.is_alias or incoming.is_alias,
            context_metadata={
                **current.context_metadata,
                **incoming.context_metadata,
            },
        )
    if target is None:
        return current
    aliases = _unique(
        [
            *current.aliases,
            *([current.name] if current.name != target.title else []),
        ]
    )
    return replace(
        current,
        aliases=aliases,
        matched_existing_key=target.document_key,
        is_alias=current.is_alias or current.name != target.title,
    )


def _merge_concepts(
    nodes: Sequence[_IncomingNode], target: ExistingWikiEntry | None
) -> ConceptClassification:
    """같은 대상으로 확정된 concept 분류 후보를 하나로 병합한다."""
    values = [node.value for node in nodes if isinstance(node.value, ConceptClassification)]
    current = values[0]
    for incoming in values[1:]:
        current = replace(
            current,
            definition=_merge_text(current.definition, incoming.definition),
            key_characteristics=_unique(
                [*current.key_characteristics, *incoming.key_characteristics]
            ),
            applications=_unique([*current.applications, *incoming.applications]),
            related_entity_names=_unique(
                [*current.related_entity_names, *incoming.related_entity_names]
            ),
            related_concepts=_unique(
                [*current.related_concepts, *incoming.related_concepts]
            ),
            aliases=_unique(
                [
                    *current.aliases,
                    *(
                        [incoming.title]
                        if incoming.title.casefold() != current.title.casefold()
                        else []
                    ),
                    *incoming.aliases,
                ]
            ),
            mentions=_unique([*current.mentions, *incoming.mentions]),
            overlaps_existing=current.overlaps_existing or incoming.overlaps_existing,
            context_metadata={
                **current.context_metadata,
                **incoming.context_metadata,
            },
        )
    if target is None:
        return current
    aliases = _unique(
        [
            *current.aliases,
            *([current.title] if current.title != target.title else []),
        ]
    )
    return replace(
        current,
        aliases=aliases,
        matched_existing_key=target.document_key,
        overlaps_existing=True,
    )


def _connected_components(
    incoming: Sequence[_IncomingNode], existing: Sequence[ExistingWikiEntry]
) -> list[tuple[list[_IncomingNode], list[ExistingWikiEntry]]]:
    """같은 정규화 표면형 또는 기존 key 지목으로 연결된 후보군을 만든다."""
    incoming_by_ref = {node.ref: node for node in incoming}
    existing_by_ref = {
        f"existing:{entry.document_kind}:{entry.document_key}": entry
        for entry in existing
    }
    surface_refs: dict[str, list[str]] = defaultdict(list)
    for node in incoming:
        for surface in _surfaces(node.label, node.aliases):
            surface_refs[surface].append(node.ref)
    for ref, entry in existing_by_ref.items():
        for surface in _surfaces(entry.title, _metadata_aliases(entry)):
            surface_refs[surface].append(ref)

    adjacency: dict[str, set[str]] = defaultdict(set)
    for refs in surface_refs.values():
        for ref in refs:
            adjacency[ref].update(other for other in refs if other != ref)
    for node in incoming:
        matched_key = getattr(node.value, "matched_existing_key", None)
        if not matched_key:
            continue
        ref = f"existing:{node.document_kind}:{matched_key}"
        if ref in existing_by_ref:
            adjacency[node.ref].add(ref)
            adjacency[ref].add(node.ref)

    components: list[tuple[list[_IncomingNode], list[ExistingWikiEntry]]] = []
    visited: set[str] = set()
    for node in incoming:
        if node.ref in visited:
            continue
        stack = [node.ref]
        refs: set[str] = set()
        while stack:
            ref = stack.pop()
            if ref in refs:
                continue
            refs.add(ref)
            stack.extend(adjacency.get(ref, ()))
        visited.update(refs)
        components.append(
            (
                [incoming_by_ref[ref] for ref in refs if ref in incoming_by_ref],
                [existing_by_ref[ref] for ref in refs if ref in existing_by_ref],
            )
        )
    return components


def prepare_wiki_identity_resolution(
    *,
    classification: WikiClassification,
    existing_entities: Sequence[ExistingWikiEntry],
    existing_concepts: Sequence[ExistingWikiEntry],
) -> WikiResolutionDraft:
    """표면형이 확실한 노드는 병합하고 의미 판정이 필요한 충돌만 추린다."""
    incoming = _incoming_nodes(classification)
    existing = [*existing_entities, *existing_concepts]
    merged_by_ref: dict[str, EntityClassification | ConceptClassification] = {}
    removed_refs: set[str] = set()
    conflicts: list[WikiIdentityConflict] = []

    for component_number, (nodes, options) in enumerate(
        _connected_components(incoming, existing), start=1
    ):
        nodes.sort(key=lambda item: item.ref)
        options.sort(key=lambda item: (item.document_kind, item.document_key))
        incoming_kinds = {node.document_kind for node in nodes}
        option_kinds = {option.document_kind for option in options}
        same_kind = len(incoming_kinds) == 1
        compatible_options = (
            len(options) <= 1 and (not options or option_kinds == incoming_kinds)
        )
        if same_kind and compatible_options:
            target = options[0] if options else None
            first_ref = nodes[0].ref
            if nodes[0].document_kind == "entity":
                merged_by_ref[first_ref] = _merge_entities(nodes, target)
            else:
                merged_by_ref[first_ref] = _merge_concepts(nodes, target)
            removed_refs.update(node.ref for node in nodes[1:])
            continue

        conflicts.append(
            WikiIdentityConflict(
                conflict_id=f"identity-{component_number}",
                incoming_refs=tuple(node.ref for node in nodes),
                incoming_labels=tuple(node.label for node in nodes),
                incoming_kinds=tuple(node.document_kind for node in nodes),
                options=tuple(
                    WikiIdentityOption(
                        document_kind=option.document_kind,
                        document_key=option.document_key,
                        title=option.title,
                        aliases=_metadata_aliases(option),
                        domain=option.domain,
                        summary=option.summary,
                    )
                    for option in options
                ),
            )
        )

    entities = [
        merged_by_ref.get(f"entity:{index}", entity)
        for index, entity in enumerate(classification.entities)
        if f"entity:{index}" not in removed_refs
    ]
    concepts = [
        merged_by_ref.get(f"concept:{index}", concept)
        for index, concept in enumerate(classification.concepts)
        if f"concept:{index}" not in removed_refs
    ]
    return WikiResolutionDraft(
        classification=replace(
            classification,
            entities=[item for item in entities if isinstance(item, EntityClassification)],
            concepts=[item for item in concepts if isinstance(item, ConceptClassification)],
        ),
        conflicts=tuple(conflicts),
    )


def _conflict_payload(
    conflict: WikiIdentityConflict, classification: WikiClassification
) -> dict[str, object]:
    """한 충돌의 후보 정보와 분류 근거를 LLM 입력 객체로 만든다."""
    incoming_details: list[dict[str, object]] = []
    wanted = list(zip(conflict.incoming_kinds, conflict.incoming_labels, strict=True))
    for kind, label in wanted:
        if kind == "entity":
            match = next(
                (
                    entity
                    for entity in classification.entities
                    if normalize_wiki_surface(entity.name)
                    == normalize_wiki_surface(label)
                ),
                None,
            )
            if match is not None:
                incoming_details.append(
                    {
                        "kind": "entity",
                        "label": match.name,
                        "subtype": match.subtype,
                        "description": match.description,
                        "aliases": match.aliases,
                        "mentions": match.mentions,
                    }
                )
        else:
            match = next(
                (
                    concept
                    for concept in classification.concepts
                    if normalize_wiki_surface(concept.title)
                    == normalize_wiki_surface(label)
                ),
                None,
            )
            if match is not None:
                incoming_details.append(
                    {
                        "kind": "concept",
                        "label": match.title,
                        "subtype": match.subtype,
                        "definition": match.definition,
                        "aliases": match.aliases,
                        "mentions": match.mentions,
                    }
                )
    return {
        "conflict_id": conflict.conflict_id,
        "incoming": incoming_details,
        "existing_options": [
            {
                "kind": option.document_kind,
                "key": option.document_key,
                "title": option.title,
                "aliases": list(option.aliases),
                "domain": option.domain,
                "summary": option.summary,
            }
            for option in conflict.options
        ],
    }


def _parse_resolution_decisions(
    raw_response: str, draft: WikiResolutionDraft
) -> list[_ResolutionDecision]:
    """LLM JSON을 허용된 conflict·기존 key만 가리키는 판정 목록으로 검증한다."""
    try:
        payload = json.loads(strip_json_fence(raw_response))
    except json.JSONDecodeError as error:
        raise ValueError(f"Wiki identity 판정 응답이 JSON 형식이 아닙니다: {error}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("resolutions"), list):
        raise ValueError("Wiki identity 판정 응답에 resolutions 배열이 없습니다.")

    conflicts = {conflict.conflict_id: conflict for conflict in draft.conflicts}
    decisions: dict[str, _ResolutionDecision] = {}
    for raw in payload["resolutions"]:
        if not isinstance(raw, dict):
            raise ValueError("Wiki identity 판정 항목이 JSON 객체가 아닙니다.")
        conflict_id = str(raw.get("conflict_id") or "").strip()
        if conflict_id not in conflicts:
            raise ValueError(f"알 수 없는 Wiki identity conflict입니다: {conflict_id}")
        if conflict_id in decisions:
            raise ValueError(f"Wiki identity conflict 판정이 중복되었습니다: {conflict_id}")
        conflict = conflicts[conflict_id]
        action = str(raw.get("action") or "").strip().lower()
        target_kind = str(raw.get("target_kind") or "").strip().lower()
        if target_kind not in {"entity", "concept"}:
            raise ValueError(f"허용되지 않은 canonical kind입니다: {target_kind}")
        target_key = str(raw.get("target_key") or "").strip() or None

        if action == "match_existing":
            option = next(
                (
                    candidate
                    for candidate in conflict.options
                    if candidate.document_kind == target_kind
                    and candidate.document_key == target_key
                ),
                None,
            )
            if option is None:
                raise ValueError(
                    f"판정 후보에 없는 기존 Wiki key입니다: {target_kind}/{target_key}"
                )
            canonical_label = option.title
        elif action == "create":
            if target_key is not None:
                raise ValueError("새 Wiki identity 생성에는 target_key를 지정할 수 없습니다.")
            requested_label = str(raw.get("canonical_label") or "").strip()
            canonical_label = next(
                (
                    label
                    for label in conflict.incoming_labels
                    if normalize_wiki_surface(label)
                    == normalize_wiki_surface(requested_label)
                ),
                "",
            )
            if not canonical_label:
                raise ValueError(
                    "새 canonical label은 incoming label 중 하나여야 합니다."
                )
        else:
            raise ValueError(f"허용되지 않은 Wiki identity action입니다: {action}")
        decisions[conflict_id] = _ResolutionDecision(
            conflict_id=conflict_id,
            action=action,
            target_kind=target_kind,
            target_key=target_key,
            canonical_label=canonical_label,
        )

    missing = [conflict_id for conflict_id in conflicts if conflict_id not in decisions]
    if missing:
        raise ValueError(f"Wiki identity 판정이 누락되었습니다: {', '.join(missing)}")
    return [decisions[conflict.conflict_id] for conflict in draft.conflicts]


def _to_entity(
    value: EntityClassification | ConceptClassification,
    canonical_label: str,
) -> EntityClassification:
    """entity·concept 후보를 canonical entity 병합 입력으로 변환한다."""
    if isinstance(value, EntityClassification):
        return replace(
            value,
            name=canonical_label,
            aliases=_unique(
                [*value.aliases, *([value.name] if value.name != canonical_label else [])]
            ),
            matched_existing_key=None,
        )
    return EntityClassification(
        name=canonical_label,
        subtype="other",
        description=value.definition,
        aliases=_unique(
            [*value.aliases, *([value.title] if value.title != canonical_label else [])]
        ),
        related_entity_names=value.related_entity_names,
        related_concepts=value.related_concepts,
        mentions=value.mentions,
        context_metadata=value.context_metadata,
    )


def _to_concept(
    value: EntityClassification | ConceptClassification,
    canonical_label: str,
) -> ConceptClassification:
    """entity·concept 후보를 canonical concept 병합 입력으로 변환한다."""
    if isinstance(value, ConceptClassification):
        return replace(
            value,
            title=canonical_label,
            aliases=_unique(
                [*value.aliases, *([value.title] if value.title != canonical_label else [])]
            ),
            matched_existing_key=None,
            overlaps_existing=False,
        )
    return ConceptClassification(
        title=canonical_label,
        subtype="term",
        definition=value.description,
        related_entity_names=value.related_entity_names,
        related_concepts=value.related_concepts,
        aliases=_unique(
            [*value.aliases, *([value.name] if value.name != canonical_label else [])]
        ),
        mentions=value.mentions,
        context_metadata=value.context_metadata,
    )


def _select_conflict_values(
    classification: WikiClassification, conflict: WikiIdentityConflict
) -> list[EntityClassification | ConceptClassification]:
    """충돌의 kind·label 쌍에 해당하는 현재 분류 후보를 순서대로 찾는다."""
    values: list[EntityClassification | ConceptClassification] = []
    used: set[int] = set()
    combined: list[tuple[str, EntityClassification | ConceptClassification]] = [
        *(('entity', entity) for entity in classification.entities),
        *(('concept', concept) for concept in classification.concepts),
    ]
    for kind, label in zip(
        conflict.incoming_kinds, conflict.incoming_labels, strict=True
    ):
        marker = normalize_wiki_surface(label)
        selected = next(
            (
                (index, value)
                for index, (candidate_kind, value) in enumerate(combined)
                if index not in used
                and candidate_kind == kind
                and normalize_wiki_surface(
                    value.name
                    if isinstance(value, EntityClassification)
                    else value.title
                )
                == marker
            ),
            None,
        )
        if selected is None:
            raise ValueError(f"Wiki identity 분류 후보를 다시 찾을 수 없습니다: {kind}/{label}")
        index, value = selected
        used.add(index)
        values.append(value)
    return values


def _rewrite_relations(
    classification: WikiClassification,
    mappings: dict[tuple[str, str], tuple[str, str, str | None]],
) -> list:
    """canonical kind·이름 변경을 관계 양 끝에 반영하고 자기 관계를 제거한다."""
    rewritten = []
    signatures: set[tuple[str, str, str, str, str]] = set()
    for relation in classification.relations:
        source = mappings.get(
            (relation.source_kind, normalize_wiki_surface(relation.source_name)),
            (
                relation.source_kind,
                relation.source_name,
                relation.source_matched_key,
            ),
        )
        target = mappings.get(
            (relation.target_kind, normalize_wiki_surface(relation.target_name)),
            (
                relation.target_kind,
                relation.target_name,
                relation.target_matched_key,
            ),
        )
        if (
            source[0] == target[0]
            and normalize_wiki_surface(source[1])
            == normalize_wiki_surface(target[1])
        ):
            continue
        if source[0] == "concept" and target[0] == "entity":
            source, target = target, source
        relation_type = {
            ("entity", "entity"): "entity_relation",
            ("entity", "concept"): "applies_concept",
            ("concept", "concept"): "related_concept",
        }.get((source[0], target[0]))
        if relation_type is None:
            continue
        signature = (
            source[0],
            normalize_wiki_surface(source[1]),
            target[0],
            normalize_wiki_surface(target[1]),
            relation_type,
        )
        if signature in signatures:
            continue
        signatures.add(signature)
        rewritten.append(
            replace(
                relation,
                source_kind=source[0],
                source_name=source[1],
                source_matched_key=source[2],
                target_kind=target[0],
                target_name=target[1],
                target_matched_key=target[2],
                relation_type=relation_type,
            )
        )
    return rewritten


def apply_wiki_identity_decisions(
    draft: WikiResolutionDraft, decisions: Sequence[_ResolutionDecision]
) -> WikiClassification:
    """검증된 판정을 분류 노드와 관계에 적용해 canonical 결과를 만든다."""
    classification = draft.classification
    entities = list(classification.entities)
    concepts = list(classification.concepts)
    mappings: dict[tuple[str, str], tuple[str, str, str | None]] = {}
    conflict_by_id = {conflict.conflict_id: conflict for conflict in draft.conflicts}
    for decision in decisions:
        conflict = conflict_by_id[decision.conflict_id]
        values = _select_conflict_values(
            replace(classification, entities=entities, concepts=concepts), conflict
        )
        for value in values:
            if isinstance(value, EntityClassification):
                entities.remove(value)
                old_kind, old_label = "entity", value.name
            else:
                concepts.remove(value)
                old_kind, old_label = "concept", value.title
            mappings[(old_kind, normalize_wiki_surface(old_label))] = (
                decision.target_kind,
                decision.canonical_label,
                decision.target_key,
            )

        target_entry = (
            ExistingWikiEntry(
                document_kind=decision.target_kind,
                document_key=decision.target_key or "",
                title=decision.canonical_label,
                domain=None,
                summary=None,
            )
            if decision.target_key
            else None
        )
        if decision.target_kind == "entity":
            values.sort(key=lambda value: not isinstance(value, EntityClassification))
            converted = [
                _IncomingNode(
                    ref=f"resolved:{index}",
                    document_kind="entity",
                    label=decision.canonical_label,
                    aliases=(),
                    value=_to_entity(value, decision.canonical_label),
                )
                for index, value in enumerate(values)
            ]
            entities.append(_merge_entities(converted, target_entry))
        else:
            values.sort(key=lambda value: not isinstance(value, ConceptClassification))
            converted = [
                _IncomingNode(
                    ref=f"resolved:{index}",
                    document_kind="concept",
                    label=decision.canonical_label,
                    aliases=(),
                    value=_to_concept(value, decision.canonical_label),
                )
                for index, value in enumerate(values)
            ]
            concepts.append(_merge_concepts(converted, target_entry))

    return replace(
        classification,
        entities=entities,
        concepts=concepts,
        relations=_rewrite_relations(classification, mappings),
    )


def resolve_wiki_identity_conflicts(
    *,
    draft: WikiResolutionDraft,
    source_title: str,
    model: str,
    completion: IdentityResolverCompletion = complete_with_usage,
) -> WikiIdentityResolutionResult:
    """남은 후보군을 한 번의 LLM 호출로 판정하고 canonical 분류를 반환한다."""
    if not draft.conflicts:
        return WikiIdentityResolutionResult(
            classification=draft.classification,
            model=_DETERMINISTIC_RESOLVER_MODEL,
            resolved_conflict_count=0,
        )
    user_prompt = json.dumps(
        {
            "source_title": source_title,
            "source_summary": draft.classification.source_summary,
            "conflicts": [
                _conflict_payload(conflict, draft.classification)
                for conflict in draft.conflicts
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    completed = completion(
        _SYSTEM_PROMPT,
        user_prompt,
        model=model,
        temperature=0,
    )
    decisions = _parse_resolution_decisions(completed.text, draft)
    return WikiIdentityResolutionResult(
        classification=apply_wiki_identity_decisions(draft, decisions),
        model=completed.model,
        resolved_conflict_count=len(decisions),
        input_tokens=completed.input_tokens,
        output_tokens=completed.output_tokens,
    )


def validate_wiki_identity_quality(
    *,
    classification: WikiClassification,
    existing_entities: Sequence[ExistingWikiEntry],
    existing_concepts: Sequence[ExistingWikiEntry],
) -> WikiClassification:
    """저장 직전 canonical 중복·잘못된 기존 key·자기 관계가 없는지 검증한다."""
    existing_keys = {
        "entity": {entry.document_key for entry in existing_entities},
        "concept": {entry.document_key for entry in existing_concepts},
    }
    surface_owners: dict[str, set[str]] = defaultdict(set)
    matched_owners: dict[tuple[str, str], set[str]] = defaultdict(set)
    for index, entity in enumerate(classification.entities):
        owner = f"entity:{index}"
        for surface in _surfaces(entity.name, entity.aliases):
            surface_owners[surface].add(owner)
        if entity.matched_existing_key:
            if entity.matched_existing_key not in existing_keys["entity"]:
                raise ValueError(
                    "존재하지 않는 기존 entity key를 저장할 수 없습니다: "
                    f"{entity.matched_existing_key}"
                )
            matched_owners[("entity", entity.matched_existing_key)].add(owner)
    for index, concept in enumerate(classification.concepts):
        owner = f"concept:{index}"
        for surface in _surfaces(concept.title, concept.aliases):
            surface_owners[surface].add(owner)
        if concept.matched_existing_key:
            if concept.matched_existing_key not in existing_keys["concept"]:
                raise ValueError(
                    "존재하지 않는 기존 concept key를 저장할 수 없습니다: "
                    f"{concept.matched_existing_key}"
                )
            matched_owners[("concept", concept.matched_existing_key)].add(owner)

    duplicate_surfaces = sorted(
        surface for surface, owners in surface_owners.items() if len(owners) > 1
    )
    if duplicate_surfaces:
        raise ValueError(
            "canonical 표면형이 여러 Wiki 노드에 남아 있습니다: "
            + ", ".join(duplicate_surfaces)
        )
    duplicate_keys = sorted(
        f"{kind}/{key}"
        for (kind, key), owners in matched_owners.items()
        if len(owners) > 1
    )
    if duplicate_keys:
        raise ValueError(
            "같은 기존 Wiki key를 여러 후보가 갱신하려 합니다: "
            + ", ".join(duplicate_keys)
        )
    for relation in classification.relations:
        if (
            relation.source_kind == relation.target_kind
            and normalize_wiki_surface(relation.source_name)
            == normalize_wiki_surface(relation.target_name)
        ):
            raise ValueError("canonical identity 자기 관계를 저장할 수 없습니다.")
    return classification
