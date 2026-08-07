"""개인 Wiki 노드의 표기 정규화와 기존 문서 후보 탐색.

띄어쓰기·구두점·대소문자 차이를 제거한 비교용 표면형을 만들고, 이번 Build의
분류 후보와 기존 entity·concept을 같은 의미 후보군으로 묶는다. 동일 kind의
대상이 하나로 확정되는 경우에는 코드로 병합하고, kind 충돌이나 복수 후보만
후속 의미 판정 단계에 넘긴다.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

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
class _IncomingNode:
    """분류 후보를 표면형 비교에 사용할 내부 노드로 표현한다."""

    ref: str
    document_kind: str
    label: str
    aliases: tuple[str, ...]
    value: EntityClassification | ConceptClassification


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
                [*current.aliases, incoming.name, *incoming.aliases]
            ),
            related_entity_names=_unique(
                [*current.related_entity_names, *incoming.related_entity_names]
            ),
            related_concepts=_unique(
                [*current.related_concepts, *incoming.related_concepts]
            ),
            mentions=_unique([*current.mentions, *incoming.mentions]),
            is_alias=current.is_alias or incoming.is_alias,
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
                [*current.aliases, incoming.title, *incoming.aliases]
            ),
            mentions=_unique([*current.mentions, *incoming.mentions]),
            overlaps_existing=current.overlaps_existing or incoming.overlaps_existing,
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
