"""이미 저장된 개인 Wiki 중복 문서를 canonical 문서로 합치는 계획 수립.

Build 경로의 identity 해소(PWIKI-008)는 저장 **전에** 중복 생성을 막는다.
이 모듈은 그와 반대로, 이미 DB에 남아 있는 과거 중복을 소급 정리할 때
필요한 최종 상태를 계산한다. LLM과 DB를 호출하지 않는 결정적 계획 함수라
유지 루프가 트랜잭션을 열기 전에 결과를 검증할 수 있다.

병합 정책은 `docs/llm-wiki-vault-structure.md` §5를 따른다. aliases와 sources는
append-only로 보존하고, `reviewed: true` 문서의 기존 내용은 덮어쓰지 않으며,
흡수된 문서의 내용은 출처와 함께 남긴다.
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from shared.wiki_models import ExistingWikiEntry, WikiRelationPlan


class CrossKindMergeError(Exception):
    """entity와 concept처럼 종류가 다른 문서를 병합하려 할 때 발생한다."""


@dataclass(frozen=True, slots=True)
class WikiMergePlan:
    """중복 문서를 흡수한 뒤 저장해야 할 canonical 문서의 최종 상태."""

    document_kind: str
    document_key: str
    title: str
    domain: str | None
    summary: str
    metadata: dict[str, object]
    relations: tuple[WikiRelationPlan, ...]
    retired_document_keys: tuple[str, ...]
    added_alias_count: int = 0
    added_source_count: int = 0
    rewritten_relation_count: int = 0
    dropped_relation_count: int = 0
    reviewed_preserved: bool = False
    merged_from: tuple[Mapping[str, object], ...] = field(default_factory=tuple)


def _dedup_key(value: str) -> str:
    """별칭·출처를 같은 값으로 볼지 판단하는 비교 키를 만든다.

    Build 경로의 별칭 병합(`identity_resolution`)과 같은 기준을 쓰려고 표기
    차이는 남기고 Unicode 정규화와 대소문자만 맞춘다. `머신러닝`과 `머신 러닝`
    처럼 띄어쓰기만 다른 표기는 사용자가 실제로 쓴 표기이므로 별칭으로 함께
    보존한다.
    """
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _metadata_strings(metadata: Mapping[str, object], key: str) -> list[str]:
    """Metadata 배열에서 비어 있지 않은 문자열만 순서대로 읽는다."""
    value = metadata.get(key)
    if not isinstance(value, (list, tuple)):
        return []
    return [normalized for item in value if (normalized := str(item).strip())]


def _metadata_list(metadata: Mapping[str, object], key: str) -> list[object]:
    """Metadata에서 배열 값만 안전하게 읽어 새 목록으로 복사한다."""
    value = metadata.get(key)
    return list(value) if isinstance(value, (list, tuple)) else []


def _append_unique(base: Iterable[str], incoming: Iterable[str]) -> tuple[list[str], int]:
    """기존 값을 보존한 채 새 표면형만 덧붙이고 추가 개수를 함께 반환한다."""
    result: list[str] = []
    seen: set[str] = set()
    for item in base:
        marker = _dedup_key(item)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    added = 0
    for item in incoming:
        marker = _dedup_key(item)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        result.append(item)
        added += 1
    return result, added


def _is_reviewed(metadata: Mapping[str, object]) -> bool:
    """사람이 검증해 보호 대상이 된 문서인지 확인한다."""
    return metadata.get("reviewed") is True


def _relation_confidence(metadata: Mapping[str, object]) -> float:
    """관계 신뢰도를 정렬 가능한 숫자로 읽고 잘못된 값은 0으로 낮춘다."""
    value = metadata.get("confidence", 1.0)
    if isinstance(value, bool):
        return 0.0
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        return 0.0
    return confidence


def _relation_signature(
    relation: WikiRelationPlan,
) -> tuple[str, str, str, str, str]:
    """관계 한 건을 결정적으로 식별하는 서명을 만든다."""
    return (
        relation.source_document_kind,
        relation.source_document_key,
        relation.target_document_kind,
        relation.target_document_key,
        relation.relation_type,
    )


def _unique_duplicates(
    winner: ExistingWikiEntry, duplicates: Sequence[ExistingWikiEntry]
) -> list[ExistingWikiEntry]:
    """흡수 대상 문서에서 canonical 문서와 중복 지정을 제거한다."""
    unique: list[ExistingWikiEntry] = []
    seen: set[str] = set()
    for duplicate in duplicates:
        if duplicate.document_kind != winner.document_kind:
            raise CrossKindMergeError(
                "종류가 다른 Wiki 문서는 결정적으로 병합할 수 없습니다: "
                f"{winner.document_kind}/{winner.document_key} vs "
                f"{duplicate.document_kind}/{duplicate.document_key}"
            )
        if duplicate.document_key == winner.document_key:
            continue
        if duplicate.document_key in seen:
            continue
        seen.add(duplicate.document_key)
        unique.append(duplicate)
    return unique


def _rewrite_relations(
    relations: Sequence[WikiRelationPlan],
    *,
    document_kind: str,
    winner_key: str,
    retired_keys: frozenset[str],
) -> tuple[tuple[WikiRelationPlan, ...], int, int]:
    """흡수된 문서를 가리키던 관계를 canonical 문서로 옮기고 중복을 정리한다.

    같은 문서 종류끼리만 병합하므로 관계 유형은 그대로 유효하다. 옮긴 뒤
    자기 자신을 가리키게 된 관계는 버리고, 서명이 같아진 관계는 신뢰도가
    가장 높은 한 건만 남긴다.
    """

    def _redirect(kind: str, key: str) -> str:
        """흡수 대상 문서를 가리키는 endpoint를 canonical key로 바꾼다."""
        if kind == document_kind and key in retired_keys:
            return winner_key
        return key

    rewritten: list[WikiRelationPlan] = []
    rewritten_count = 0
    dropped_count = 0
    for relation in relations:
        source_key = _redirect(
            relation.source_document_kind, relation.source_document_key
        )
        target_key = _redirect(
            relation.target_document_kind, relation.target_document_key
        )
        changed = (
            source_key != relation.source_document_key
            or target_key != relation.target_document_key
        )
        if (
            relation.source_document_kind == relation.target_document_kind
            and source_key == target_key
        ):
            dropped_count += 1
            continue
        if changed:
            rewritten_count += 1
            relation = WikiRelationPlan(
                source_document_key=source_key,
                source_document_kind=relation.source_document_kind,
                target_document_key=target_key,
                target_document_kind=relation.target_document_kind,
                relation_type=relation.relation_type,
                metadata=dict(relation.metadata),
            )
        rewritten.append(relation)

    # 입력 순서가 달라도 같은 결과를 내도록 서명·신뢰도로 정렬한 뒤 고른다.
    ordered = sorted(
        rewritten,
        key=lambda item: (
            _relation_signature(item),
            -_relation_confidence(item.metadata),
        ),
    )
    selected: dict[tuple[str, str, str, str, str], WikiRelationPlan] = {}
    for relation in ordered:
        signature = _relation_signature(relation)
        if signature in selected:
            dropped_count += 1
            continue
        selected[signature] = relation
    return tuple(selected.values()), rewritten_count, dropped_count


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def pwiki_009(
    winner: ExistingWikiEntry,
    duplicates: Sequence[ExistingWikiEntry],
    relations: Sequence[WikiRelationPlan] = (),
) -> WikiMergePlan:
    """[PWIKI-009] Wiki 문서 병합.

    유사한 사용자 지식을 하나의 문서나 주제로 병합한다. 흡수 대상 문서의
    제목·별칭·출처를 canonical 문서에 append-only로 옮기고, 이들을 가리키던
    관계를 canonical 문서로 이어 붙인 최종 상태를 계산한다. DB는 건드리지
    않으므로 호출자가 결과를 검증한 뒤 하나의 Transaction에서 반영한다.

    Args:
        winner: 병합 후 살아남을 canonical 문서
        duplicates: canonical 문서로 흡수할 중복 문서 목록
        relations: 현재 Wiki Snapshot의 관계 목록 (endpoint 재지정 대상)

    Returns:
        canonical 문서의 최종 상태와 정리된 관계, 폐기 대상 문서 Key

    Raises:
        ValueError: 흡수할 중복 문서가 없는 경우
        CrossKindMergeError: entity와 concept처럼 종류가 다른 문서를 넘긴 경우
    """
    if winner.document_kind not in {"entity", "concept"}:
        raise ValueError(f"병합할 수 없는 Wiki 문서 유형입니다: {winner.document_kind}")
    if not winner.document_key:
        raise ValueError("PWIKI-009에 canonical document_key가 필요합니다.")
    absorbed = _unique_duplicates(winner, duplicates)
    if not absorbed:
        raise ValueError("PWIKI-009에 흡수할 중복 Wiki 문서가 필요합니다.")

    metadata = dict(winner.metadata)
    reviewed = _is_reviewed(metadata)

    # 흡수한 문서의 제목은 canonical 문서를 찾는 별칭으로 계속 살아 있어야 한다.
    incoming_aliases: list[str] = []
    incoming_sources: list[str] = []
    for duplicate in absorbed:
        incoming_aliases.append(duplicate.title)
        incoming_aliases.extend(_metadata_strings(duplicate.metadata, "aliases"))
        incoming_sources.extend(_metadata_strings(duplicate.metadata, "sources"))

    winner_marker = _dedup_key(winner.title)
    aliases, added_alias_count = _append_unique(
        _metadata_strings(metadata, "aliases"),
        (alias for alias in incoming_aliases if _dedup_key(alias) != winner_marker),
    )
    sources, added_source_count = _append_unique(
        _metadata_strings(metadata, "sources"), incoming_sources
    )
    if aliases:
        metadata["aliases"] = aliases
    if sources:
        metadata["sources"] = sources

    # 흡수된 내용은 요약을 덮어쓰지 않고 출처와 함께 남겨 근거를 잃지 않는다.
    merged_from = tuple(
        {
            "document_kind": duplicate.document_kind,
            "document_key": duplicate.document_key,
            "title": duplicate.title,
            "summary": duplicate.summary or "",
            "sources": _metadata_strings(duplicate.metadata, "sources"),
        }
        for duplicate in absorbed
    )
    metadata["merged_from"] = [
        *_metadata_list(metadata, "merged_from"),
        *merged_from,
    ]

    # 기존 모순 기록은 그대로 이어받되 병합이 새 모순을 지어내지는 않는다.
    contradictions = _metadata_list(metadata, "contradictions")
    for duplicate in absorbed:
        contradictions.extend(_metadata_list(duplicate.metadata, "contradictions"))
    if contradictions:
        metadata["contradictions"] = contradictions

    domain = winner.domain
    summary = winner.summary or ""
    if not reviewed:
        # 검증되지 않은 문서에서만 비어 있는 값을 흡수 대상에서 채운다.
        if domain is None:
            domain = next(
                (
                    duplicate.domain
                    for duplicate in absorbed
                    if duplicate.domain is not None
                ),
                None,
            )
        if not summary:
            summary = next(
                (
                    duplicate.summary
                    for duplicate in absorbed
                    if duplicate.summary
                ),
                "",
            )

    retired_keys = tuple(duplicate.document_key for duplicate in absorbed)
    merged_relations, rewritten_count, dropped_count = _rewrite_relations(
        relations,
        document_kind=winner.document_kind,
        winner_key=winner.document_key,
        retired_keys=frozenset(retired_keys),
    )
    return WikiMergePlan(
        document_kind=winner.document_kind,
        document_key=winner.document_key,
        title=winner.title,
        domain=domain,
        summary=summary,
        metadata=metadata,
        relations=merged_relations,
        retired_document_keys=retired_keys,
        added_alias_count=added_alias_count,
        added_source_count=added_source_count,
        rewritten_relation_count=rewritten_count,
        dropped_relation_count=dropped_count,
        reviewed_preserved=reviewed,
        merged_from=merged_from,
    )
