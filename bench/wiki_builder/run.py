"""개인 LLM Wiki Builder 품질 벤치마크 실행기.

실제 OpenAI API를 호출해 노드·관계 추출뿐 아니라 canonical 병합,
관계 disposition, stale 관계 제거와 active degree 안정성을 함께 평가한다.
실행 전 예상 비용을 표시하고 명시적 승인 옵션이 있을 때만 호출한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

# OPENAI_API_KEY를 .env에서 읽는다(앱 진입점과 같은 방식).
load_dotenv(PROJECT_ROOT / ".env")

from agent.llm.api import complete_with_usage
from agent.wiki_builder.api import (
    RelationCandidateQuery,
    WikiGraphEdge,
    WikiNodeIdentity,
    WikiRelationCandidate,
    build_wiki_plan,
    link_wiki_relations,
    prepare_wiki_identity_resolution,
    retrieve_wiki_relation_candidates,
)
from agent.wiki_builder.features import classification
from shared.wiki_models import ExistingWikiEntry, WikiRelationPlan

ROOT = Path(__file__).resolve().parent
ESTIMATED_OUTPUT_TOKENS_PER_CASE = 1_400
ESTIMATED_PROMPT_OVERHEAD_TOKENS_PER_CASE = 5_000
_INACTIVE_RELATION_STATUSES = {"rejected", "stale", "superseded"}
_RELATION_STATE_SCHEMA_VERSION = 1
_RELATION_STATE_PROVIDER = (
    "sync_wiki_relation_supports/list_existing_wiki_relations"
)
_RELATION_STATE_KIND = "post_sync_active_relation_heads"
_LIFECYCLE_EXPECTATION_KEYS = (
    "removed_relations",
    "active_degree_by_document",
    "verified_degree_by_document",
)
_RELATION_PROVENANCE_KINDS = {
    "source_explicit",
    "semantic_inference",
    "user_declared",
    "system_rule",
}
_ACTIVE_REVIEW_STATUSES = {"unreviewed", "accepted"}


@dataclass(slots=True)
class Usage:
    """벤치마크 전체의 입력·출력 토큰을 누적한다."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class AuthoritativeRelationStates:
    """영속화 동기화 뒤 조회한 active 관계 head Fixture를 보관한다."""

    source_path: Path
    sha256: str
    states_by_case: dict[str, tuple[WikiRelationPlan, ...]]

    def for_case(self, case_id: str) -> tuple[WikiRelationPlan, ...] | None:
        """케이스 ID에 대응하는 post-sync active 관계 상태를 반환한다."""
        return self.states_by_case.get(case_id)


def _args() -> argparse.Namespace:
    """모델·토큰 단가와 실제 호출 비용 승인 옵션을 파싱한다."""
    parser = argparse.ArgumentParser(description="Personal Wiki LLM benchmark")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--input-cost-per-million", type=float, required=True)
    parser.add_argument("--output-cost-per-million", type=float, required=True)
    parser.add_argument(
        "--relation-state-fixture",
        type=Path,
        help=(
            "sync_wiki_relation_supports 뒤 active head 조회 결과 Fixture. "
            "lifecycle 기대값이 있는 데이터셋은 필수다."
        ),
    )
    parser.add_argument(
        "--confirm-cost",
        action="store_true",
        help="표시된 예상 비용을 확인하고 실제 LLM 호출을 승인한다.",
    )
    return parser.parse_args()


def _load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    """JSONL 데이터셋을 읽고 원본을 훼손하지 않은 채 긴 입력을 확장한다."""
    cases: list[dict[str, Any]] = []
    dataset = path or ROOT / "dataset.jsonl"
    for line in dataset.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        payload = dict(case["input"])
        repeat = payload.pop("repeat", None)
        suffix = str(payload.pop("suffix", ""))
        if repeat:
            payload["content"] += repeat["text"] * int(repeat["count"])
        payload["content"] += suffix
        case["input"] = payload
        cases.append(case)
    return cases


def _requires_relation_state(case: Mapping[str, Any]) -> bool:
    """stale 또는 degree 기대값 때문에 권위 관계 상태가 필요한지 판단한다."""
    expected = case.get("expected", {})
    if not isinstance(expected, Mapping):
        return False
    return any(bool(expected.get(key)) for key in _LIFECYCLE_EXPECTATION_KEYS)


def _lifecycle_case_fingerprint(case: Mapping[str, Any]) -> str:
    """lifecycle 입력·기대값 변경을 감지할 재현 가능한 SHA-256을 만든다."""
    expected = case.get("expected", {})
    if not isinstance(expected, Mapping):
        expected = {}
    payload = {
        "id": case.get("id"),
        "input": case.get("input", {}),
        "expected": {
            key: expected.get(key)
            for key in (
                *_LIFECYCLE_EXPECTATION_KEYS,
                "verified_degree_min_confidence",
            )
            if key in expected
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_active_relation_head(
    relation: WikiRelationPlan,
    *,
    case_id: str,
) -> None:
    """Fixture 관계가 실제 active head 조회 계약을 충족하는지 검증한다."""
    metadata = relation.metadata
    status = str(metadata.get("status") or "")
    review_status = str(metadata.get("review_status") or "")
    provenance_kind = str(metadata.get("provenance_kind") or "")
    if status != "active":
        raise ValueError(
            f"{case_id}: relation status는 active여야 합니다: {status!r}"
        )
    if review_status not in _ACTIVE_REVIEW_STATUSES:
        raise ValueError(
            f"{case_id}: active head review_status가 유효하지 않습니다: "
            f"{review_status!r}"
        )
    if provenance_kind not in _RELATION_PROVENANCE_KINDS:
        raise ValueError(
            f"{case_id}: provenance_kind가 유효하지 않습니다: "
            f"{provenance_kind!r}"
        )
    try:
        confidence = float(metadata["confidence"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            f"{case_id}: active head confidence가 필요합니다."
        ) from error
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(
            f"{case_id}: confidence는 0 이상 1 이하여야 합니다: {confidence}"
        )


def _load_authoritative_relation_states(
    cases: Sequence[Mapping[str, Any]],
    path: Path | None,
) -> AuthoritativeRelationStates | None:
    """명시적 Fixture를 읽고 모든 lifecycle 케이스의 상태를 사전 검증한다.

    Fixture는 ``sync_wiki_relation_supports`` 실행 뒤
    ``list_existing_wiki_relations``가 조회한 active·non-rejected 관계 head만
    담는다. 다른 원본 support의 존재를 알 수 없는 Build Plan을 관계 상태로
    추정하지 않는다.
    """
    lifecycle_cases = [case for case in cases if _requires_relation_state(case)]
    if not lifecycle_cases:
        return None
    if path is None:
        raise ValueError(
            "lifecycle 기대값이 있어 --relation-state-fixture가 필요합니다. "
            "DB 동기화 후 active head Fixture 없이는 유료 LLM 호출을 시작하지 "
            "않습니다."
        )
    try:
        fixture_bytes = path.read_bytes()
    except OSError as error:
        raise ValueError(f"관계 상태 Fixture를 읽을 수 없습니다: {path}") from error
    try:
        fixture = json.loads(fixture_bytes)
    except json.JSONDecodeError as error:
        raise ValueError(f"관계 상태 Fixture JSON이 유효하지 않습니다: {path}") from error
    if not isinstance(fixture, Mapping):
        raise ValueError("관계 상태 Fixture 최상위 값은 JSON object여야 합니다.")
    if fixture.get("schema_version") != _RELATION_STATE_SCHEMA_VERSION:
        raise ValueError(
            "관계 상태 Fixture schema_version이 다릅니다: "
            f"{fixture.get('schema_version')!r}"
        )
    if fixture.get("provider") != _RELATION_STATE_PROVIDER:
        raise ValueError(
            "관계 상태 Fixture provider가 영속화 계약과 다릅니다: "
            f"{fixture.get('provider')!r}"
        )
    if fixture.get("state_kind") != _RELATION_STATE_KIND:
        raise ValueError(
            "관계 상태 Fixture state_kind가 active head 조회가 아닙니다: "
            f"{fixture.get('state_kind')!r}"
        )
    fixture_cases = fixture.get("cases")
    if not isinstance(fixture_cases, Mapping):
        raise ValueError("관계 상태 Fixture cases는 JSON object여야 합니다.")

    states_by_case: dict[str, tuple[WikiRelationPlan, ...]] = {}
    for case in lifecycle_cases:
        case_id = str(case.get("id") or "")
        fixture_case = fixture_cases.get(case_id)
        if not isinstance(fixture_case, Mapping):
            raise ValueError(f"{case_id}: 관계 상태 Fixture가 없습니다.")
        wanted_fingerprint = _lifecycle_case_fingerprint(case)
        actual_fingerprint = fixture_case.get("case_fingerprint")
        if actual_fingerprint != wanted_fingerprint:
            raise ValueError(
                f"{case_id}: 관계 상태 Fixture fingerprint가 데이터셋과 "
                "일치하지 않습니다."
            )
        raw_relations = fixture_case.get("relations")
        if not isinstance(raw_relations, list):
            raise ValueError(f"{case_id}: relations는 JSON array여야 합니다.")
        try:
            relations = _existing_relations(raw_relations)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                f"{case_id}: 관계 상태 Fixture relation 형식이 잘못되었습니다."
            ) from error
        signatures: set[tuple[str, str, str, str, str]] = set()
        for relation in relations:
            _validate_active_relation_head(relation, case_id=case_id)
            signature = _plan_relation_signature(relation)
            if signature in signatures:
                raise ValueError(f"{case_id}: 중복 active 관계 head가 있습니다.")
            signatures.add(signature)
        states_by_case[case_id] = tuple(relations)

    return AuthoritativeRelationStates(
        source_path=path.resolve(),
        sha256=hashlib.sha256(fixture_bytes).hexdigest(),
        states_by_case=states_by_case,
    )


def _estimate_tokens(cases: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """비용 승인 전에 입력·출력 토큰을 보수적으로 추정한다."""
    content_chars = sum(
        len(str(case.get("input", {}).get("content", ""))) for case in cases
    )
    estimated_input = (
        content_chars // 3
        + len(cases) * ESTIMATED_PROMPT_OVERHEAD_TOKENS_PER_CASE
    )
    estimated_output = len(cases) * ESTIMATED_OUTPUT_TOKENS_PER_CASE
    return estimated_input, estimated_output


def _estimated_cost(
    input_tokens: int,
    output_tokens: int,
    *,
    input_cost_per_million: float,
    output_cost_per_million: float,
) -> float:
    """예상 입력·출력 토큰을 사용자 제공 단가로 환산한다."""
    return (
        input_tokens * input_cost_per_million
        + output_tokens * output_cost_per_million
    ) / 1_000_000


def _names(items: list[object], attribute: str) -> dict[str, object]:
    """분류 결과를 이름의 casefold 값으로 찾을 수 있는 Map으로 만든다."""
    return {str(getattr(item, attribute)).casefold(): item for item in items}


def _field(value: object, name: str, default: object = None) -> object:
    """객체와 Mapping 양쪽에서 같은 이름의 필드를 안전하게 읽는다."""
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _relation_signature(relation: object) -> tuple[str, str, str, str, str]:
    """분류 관계를 대소문자에 무관한 채점용 Signature로 변환한다."""
    return (
        str(_field(relation, "source_kind", "")).casefold(),
        str(_field(relation, "source_name", "")).casefold(),
        str(_field(relation, "target_kind", "")).casefold(),
        str(_field(relation, "target_name", "")).casefold(),
        str(_field(relation, "relation_type", "")).casefold(),
    )


def _plan_relation_signature(
    relation: object,
) -> tuple[str, str, str, str, str]:
    """저장 계획 관계를 kind·document_key 기반 Signature로 변환한다."""
    return (
        str(_field(relation, "source_document_kind", "")).casefold(),
        str(_field(relation, "source_document_key", "")).casefold(),
        str(_field(relation, "target_document_kind", "")).casefold(),
        str(_field(relation, "target_document_key", "")).casefold(),
        str(_field(relation, "relation_type", "")).casefold(),
    )


def _expected_relation_signature(
    relation: Mapping[str, object],
) -> tuple[str, str, str, str, str]:
    """Dataset 관계 기대값을 실제 결과와 같은 Signature로 변환한다."""
    return (
        str(relation.get("source_kind", "*")).casefold(),
        str(relation.get("source_name", "*")).casefold(),
        str(relation.get("target_kind", "*")).casefold(),
        str(relation.get("target_name", "*")).casefold(),
        str(relation.get("relation_type", "*")).casefold(),
    )


def _expected_plan_relation_signature(
    relation: Mapping[str, object],
) -> tuple[str, str, str, str, str]:
    """Dataset의 저장 관계 기대값을 document_key Signature로 변환한다."""
    return (
        str(
            relation.get("source_document_kind", relation.get("source_kind", "*"))
        ).casefold(),
        str(
            relation.get("source_document_key", relation.get("source_key", "*"))
        ).casefold(),
        str(
            relation.get("target_document_kind", relation.get("target_kind", "*"))
        ).casefold(),
        str(
            relation.get("target_document_key", relation.get("target_key", "*"))
        ).casefold(),
        str(relation.get("relation_type", "*")).casefold(),
    )


def _reversed_signature(
    signature: tuple[str, str, str, str, str],
) -> tuple[str, str, str, str, str]:
    """방향만 뒤집은 관계 Signature를 만든다."""
    source_kind, source_name, target_kind, target_name, relation_type = signature
    return (target_kind, target_name, source_kind, source_name, relation_type)


def _signature_matches(
    actual: tuple[str, str, str, str, str],
    expected: tuple[str, str, str, str, str],
) -> bool:
    """별표 wildcard를 허용해 실제 관계와 기대 관계를 비교한다."""
    return all(wanted == "*" or value == wanted for value, wanted in zip(actual, expected))


def _relation_metadata(relation: object) -> dict[str, object]:
    """관계 객체의 metadata를 문자열 키 Dictionary로 정규화한다."""
    metadata = _field(relation, "metadata", {})
    if not isinstance(metadata, Mapping):
        return {}
    return {str(key): value for key, value in metadata.items()}


def _relation_attribute(relation: object, name: str) -> object:
    """관계의 일급 필드를 우선하고 없으면 하위 호환 metadata에서 읽는다."""
    direct = _field(relation, name)
    if direct is not None:
        return direct
    return _relation_metadata(relation).get(name)


def _is_active_relation(relation: object) -> bool:
    """superseded·rejected 관계를 active 그래프 계산에서 제외한다."""
    metadata = _relation_metadata(relation)
    if metadata.get("active") is False:
        return False
    status = str(_relation_attribute(relation, "status") or "active").casefold()
    review_status = str(
        _relation_attribute(relation, "review_status") or "unreviewed"
    ).casefold()
    return (
        status not in _INACTIVE_RELATION_STATUSES
        and review_status not in _INACTIVE_RELATION_STATUSES
    )


def _is_verified_relation(relation: object, *, min_confidence: float) -> bool:
    """사용자 화면의 verified degree에 포함할 승인 관계인지 판단한다."""
    if not _is_active_relation(relation):
        return False
    review_status = str(
        _relation_attribute(relation, "review_status") or "unreviewed"
    ).casefold()
    if review_status != "accepted":
        return False
    raw_confidence = _relation_attribute(relation, "confidence")
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        return False
    return confidence >= min_confidence


def _existing_entries(
    items: Sequence[Mapping[str, object]], *, document_kind: str
) -> list[ExistingWikiEntry]:
    """Dataset의 기존 Wiki 문서 JSON을 공유 값 객체로 변환한다."""
    return [
        ExistingWikiEntry(
            document_kind=str(item.get("document_kind") or document_kind),
            document_key=str(item["document_key"]),
            title=str(item["title"]),
            domain=str(item["domain"]) if item.get("domain") is not None else None,
            summary=(
                str(item["summary"]) if item.get("summary") is not None else None
            ),
            metadata=dict(item.get("metadata") or {}),
        )
        for item in items
    ]


def _existing_relations(
    items: Sequence[Mapping[str, object]],
) -> list[WikiRelationPlan]:
    """Dataset의 기존 관계 JSON을 증분 계획용 값 객체로 변환한다."""
    return [
        WikiRelationPlan(
            source_document_key=str(item["source_document_key"]),
            source_document_kind=str(item["source_document_kind"]),
            target_document_key=str(item["target_document_key"]),
            target_document_kind=str(item["target_document_kind"]),
            relation_type=str(item["relation_type"]),
            metadata=dict(item.get("metadata") or {}),
        )
        for item in items
    ]


def _onboarding_anchor_ids(
    entries: Sequence[ExistingWikiEntry],
) -> set[WikiNodeIdentity]:
    """기존 문서 metadata에서 온보딩 관심 anchor identity를 찾는다."""
    anchors: set[WikiNodeIdentity] = set()
    for entry in entries:
        source_types = entry.metadata.get("source_types", [])
        is_seed = (
            isinstance(source_types, list) and "onboarding_seed" in source_types
        ) or entry.metadata.get("onboarding_anchor") is True
        if is_seed:
            anchors.add(WikiNodeIdentity(entry.document_kind, entry.document_key))
    return anchors


def _graph_edges(relations: Sequence[WikiRelationPlan]) -> list[WikiGraphEdge]:
    """기존 active 관계 계획을 후보 검색용 무방향 1-hop edge로 변환한다."""
    edges: list[WikiGraphEdge] = []
    for relation in relations:
        if not _is_active_relation(relation):
            continue
        raw_weight = _relation_attribute(relation, "confidence")
        try:
            weight = float(raw_weight) if raw_weight is not None else 1.0
        except (TypeError, ValueError):
            weight = 1.0
        edges.append(
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
                weight=max(0.0, min(1.0, weight)),
            )
        )
    return edges


def _relation_candidates(
    result: object,
    *,
    existing_entries: Sequence[ExistingWikiEntry],
    existing_relations: Sequence[WikiRelationPlan],
) -> dict[str, list[WikiRelationCandidate]]:
    """모든 신규·갱신 노드에 하이브리드 기존 Wiki 후보를 준비한다."""
    graph_edges = _graph_edges(existing_relations)
    anchors = _onboarding_anchor_ids(existing_entries)
    queries: list[tuple[str, RelationCandidateQuery]] = []
    next_index = 1
    for entity in result.entities:
        matched = (
            WikiNodeIdentity("entity", entity.matched_existing_key)
            if entity.matched_existing_key
            else None
        )
        queries.append(
            (
                f"N{next_index}",
                RelationCandidateQuery(
                    label=entity.name,
                    aliases=tuple(entity.aliases),
                    context=entity.description,
                    matched_existing_identity=matched,
                ),
            )
        )
        next_index += 1
    for concept in result.concepts:
        matched = (
            WikiNodeIdentity("concept", concept.matched_existing_key)
            if concept.matched_existing_key
            else None
        )
        queries.append(
            (
                f"N{next_index}",
                RelationCandidateQuery(
                    label=concept.title,
                    aliases=tuple(concept.aliases),
                    context=concept.definition,
                    matched_existing_identity=matched,
                ),
            )
        )
        next_index += 1
    return {
        reference: retrieve_wiki_relation_candidates(
            query,
            existing_entries,
            graph_edges=graph_edges,
            onboarding_anchor_ids=anchors,
        )
        for reference, query in queries
    }


def _node_for_expected(result: object, expected: Mapping[str, object]) -> object | None:
    """kind와 입력 label로 분류 결과의 canonical 채점 대상 노드를 찾는다."""
    kind = str(expected["kind"])
    name = str(expected.get("name") or expected.get("incoming_name") or "").casefold()
    items = result.entities if kind == "entity" else result.concepts
    attribute = "name" if kind == "entity" else "title"
    for item in items:
        labels = {
            str(getattr(item, attribute)).casefold(),
            *(str(alias).casefold() for alias in getattr(item, "aliases", [])),
        }
        if name in labels:
            return item
    return None


def _node_disposition(
    result: object, *, kind: str, node: object
) -> tuple[str, str]:
    """명시적 disposition·사유를 우선하고 없으면 상태로 추론한다."""
    if getattr(node, "matched_existing_key", None):
        fallback = "merge"
    else:
        fallback = ""
    attribute = "name" if kind == "entity" else "title"
    markers = {
        str(getattr(node, attribute)).casefold(),
        str(getattr(node, "matched_existing_key", "") or "").casefold(),
    }
    for disposition in getattr(result, "node_dispositions", []):
        disposition_kind = str(_field(disposition, "node_kind", ""))
        disposition_markers = {
            str(_field(disposition, "node_name", "")).casefold(),
            str(
                _field(disposition, "matched_existing_key", "") or ""
            ).casefold(),
        }
        if disposition_kind == kind and markers.intersection(disposition_markers):
            value = str(_field(disposition, "disposition", ""))
            reason = str(_field(disposition, "reason", "") or "")
            return value, reason
    explicit = getattr(node, "disposition", None)
    if explicit:
        return str(explicit), str(getattr(node, "disposition_reason", "") or "")
    if fallback:
        return fallback, "canonical identity가 기존 Wiki 노드와 일치"
    endpoints: set[tuple[str, str]] = set()
    for relation in result.relations:
        if not _is_active_relation(relation):
            continue
        endpoints.add(
            (
                str(_field(relation, "source_kind", "")),
                str(_field(relation, "source_name", "")).casefold(),
            )
        )
        endpoints.add(
            (
                str(_field(relation, "target_kind", "")),
                str(_field(relation, "target_name", "")).casefold(),
            )
        )
        for side in ("source", "target"):
            matched_key = _field(relation, f"{side}_matched_key")
            relation_kind = str(_field(relation, f"{side}_kind", ""))
            if matched_key:
                endpoints.add((relation_kind, str(matched_key).casefold()))
    if any((kind, marker) in endpoints for marker in markers):
        return "connect", "품질 게이트를 통과한 관계가 있음"
    return "standalone", "검증된 관계를 확정하지 못함"


def _degree_by_document(
    relations: Sequence[object], *, verified: bool, min_confidence: float
) -> dict[str, int]:
    """active 또는 verified 관계의 양 endpoint degree를 document_key별로 계산한다."""
    degree: dict[str, int] = defaultdict(int)
    for relation in relations:
        included = (
            _is_verified_relation(relation, min_confidence=min_confidence)
            if verified
            else _is_active_relation(relation)
        )
        if not included:
            continue
        signature = _plan_relation_signature(relation)
        degree[f"{signature[0]}:{signature[1]}"] += 1
        degree[f"{signature[2]}:{signature[3]}"] += 1
    return dict(degree)


def _empty_stats(expected: Mapping[str, Any]) -> dict[str, int]:
    """실행 실패 때도 모든 집계 열을 유지하는 초기 통계를 만든다."""
    return {
        "tp": 0,
        "fn": 0,
        "fp": 0,
        "forbidden_hit": 0,
        "unsupported_edge": 0,
        "reversed_only": 0,
        "unjudged": 0,
        "judged": 0,
        "canonical_correct": 0,
        "canonical_total": len(expected.get("canonical_matches", [])),
        "disposition_correct": 0,
        "disposition_total": len(expected.get("dispositions", [])),
        "stale_correct": 0,
        "stale_total": len(expected.get("removed_relations", [])),
        "degree_correct": 0,
        "degree_total": len(expected.get("active_degree_by_document", {}))
        + len(expected.get("verified_degree_by_document", {})),
        "relation_attribute_correct": 0,
        "relation_attribute_total": sum(
            len(item.get("attributes", {}))
            for item in expected.get("relation_attributes", [])
        ),
    }


def _score_plan(
    plan: object,
    expected: Mapping[str, Any],
    *,
    errors: list[str],
    stats: dict[str, int],
) -> None:
    """증분 계획에서 권위 DB 상태와 무관한 고립 노드 수를 채점한다."""
    isolated_expected = expected.get("isolated_node_count")
    if isolated_expected is None:
        return
    stats["disposition_total"] += 1
    isolated_actual = int(getattr(plan, "isolated_node_count", -1))
    if isolated_actual == int(isolated_expected):
        stats["disposition_correct"] += 1
    else:
        errors.append(f"isolated node count: {isolated_actual} != {isolated_expected}")


def _score_relation_state(
    relations: Sequence[object] | None,
    expected: Mapping[str, Any],
    *,
    errors: list[str],
    stats: dict[str, int],
) -> None:
    """지원 동기화 후 DB 관계 head의 stale 처리와 degree를 채점한다."""
    has_lifecycle_expectation = bool(
        expected.get("removed_relations")
        or expected.get("active_degree_by_document")
        or expected.get("verified_degree_by_document")
    )
    if not has_lifecycle_expectation:
        return
    if relations is None:
        errors.append(
            "relation lifecycle state unavailable: "
            "sync_wiki_relation_supports 이후 active head 조회가 필요합니다."
        )
        return

    active_signatures = [
        _plan_relation_signature(relation)
        for relation in relations
        if _is_active_relation(relation)
    ]
    for removed in expected.get("removed_relations", []):
        signature = _expected_plan_relation_signature(removed)
        if any(_signature_matches(actual, signature) for actual in active_signatures):
            errors.append(
                "stale relation remains active: "
                f"{signature[0]}:{signature[1]} -> {signature[2]}:{signature[3]}"
            )
        else:
            stats["stale_correct"] += 1

    min_confidence = float(expected.get("verified_degree_min_confidence", 0.7))
    degree_specs = (
        (
            "active",
            expected.get("active_degree_by_document", {}),
            _degree_by_document(
                relations,
                verified=False,
                min_confidence=min_confidence,
            ),
        ),
        (
            "verified",
            expected.get("verified_degree_by_document", {}),
            _degree_by_document(
                relations,
                verified=True,
                min_confidence=min_confidence,
            ),
        ),
    )
    for degree_kind, wanted_degrees, actual_degrees in degree_specs:
        for document, wanted in wanted_degrees.items():
            actual = actual_degrees.get(str(document).casefold(), 0)
            if actual == int(wanted):
                stats["degree_correct"] += 1
            else:
                errors.append(
                    f"{degree_kind} degree: {document}={actual} != {wanted}"
                )


def _score_relation_attributes(
    result: object,
    expected: Mapping[str, Any],
    *,
    errors: list[str],
    stats: dict[str, int],
) -> None:
    """관계 provenance·confidence·review 필드가 기대 계약과 맞는지 채점한다."""
    for item in expected.get("relation_attributes", []):
        relation_spec = item.get("relation", {})
        signature = _expected_relation_signature(relation_spec)
        actual = next(
            (
                relation
                for relation in result.relations
                if _signature_matches(_relation_signature(relation), signature)
            ),
            None,
        )
        for attribute, wanted in item.get("attributes", {}).items():
            if actual is None:
                errors.append(
                    "missing relation attributes target: "
                    f"{relation_spec.get('source_name')} -> "
                    f"{relation_spec.get('target_name')}"
                )
                continue
            attribute_name = str(attribute)
            comparison = "exact"
            if attribute_name.endswith("_min"):
                attribute_name = attribute_name.removesuffix("_min")
                comparison = "min"
            elif attribute_name.endswith("_max"):
                attribute_name = attribute_name.removesuffix("_max")
                comparison = "max"
            elif attribute_name.endswith("_required"):
                attribute_name = attribute_name.removesuffix("_required")
                comparison = "required"
            value = _relation_attribute(actual, attribute_name)
            if comparison == "min":
                try:
                    matched = float(value) >= float(wanted)
                except (TypeError, ValueError):
                    matched = False
            elif comparison == "max":
                try:
                    matched = float(value) <= float(wanted)
                except (TypeError, ValueError):
                    matched = False
            elif comparison == "required":
                matched = bool(str(value or "").strip()) is bool(wanted)
            elif attribute_name == "confidence":
                try:
                    matched = abs(float(value) - float(wanted)) <= 1e-6
                except (TypeError, ValueError):
                    matched = False
            else:
                matched = value == wanted
            if matched:
                stats["relation_attribute_correct"] += 1
            else:
                errors.append(
                    f"relation attribute: {attribute}={value!r} != {wanted!r}"
                )


def _score(
    result: object,
    expected: dict[str, Any],
    *,
    plan: object | None = None,
    relation_state: Sequence[object] | None = None,
) -> tuple[bool, list[str], dict[str, int]]:
    """노드·관계·canonical·증분 계획을 Dataset 품질 기준으로 채점한다."""
    errors: list[str] = []
    stats = _empty_stats(expected)
    entities = _names(result.entities, "name")
    concepts = _names(result.concepts, "title")
    for name in expected.get("entities", []):
        if name.casefold() not in entities:
            errors.append(f"missing entity: {name}")
    for name in expected.get("concepts", []):
        if name.casefold() not in concepts:
            errors.append(f"missing concept: {name}")
    for name in expected.get("forbidden_entities", []):
        if name.casefold() in entities:
            errors.append(f"forbidden entity: {name}")
    if len(entities) > expected.get("max_entities", 10_000):
        errors.append(f"too many entities: {len(entities)}")
    if len(concepts) > expected.get("max_concepts", 10_000):
        errors.append(f"too many concepts: {len(concepts)}")
    for name, subtype in expected.get("entity_subtypes", {}).items():
        entity = entities.get(name.casefold())
        if entity and entity.subtype != subtype:
            errors.append(f"entity subtype: {name}={entity.subtype}")
    for name, subtype in expected.get("concept_subtypes", {}).items():
        concept = concepts.get(name.casefold())
        if concept and concept.subtype != subtype:
            errors.append(f"concept subtype: {name}={concept.subtype}")
    for name, aliases in expected.get("entity_aliases", {}).items():
        entity = entities.get(name.casefold())
        if entity:
            actual = {alias.casefold() for alias in entity.aliases}
            for alias in aliases:
                if alias.casefold() not in actual:
                    errors.append(f"missing alias: {name}/{alias}")
    mentions = {
        mention
        for item in [*result.entities, *result.concepts]
        for mention in item.mentions
    }
    for mention in expected.get("required_mentions", []):
        if mention not in mentions:
            errors.append(f"missing mention: {mention}")
    summary = result.source_summary.casefold()
    for term in expected.get("required_summary_terms", []):
        if term.casefold() not in summary:
            errors.append(f"missing summary term: {term}")
    relations = {
        _relation_signature(relation)
        for relation in result.relations
        if _is_active_relation(relation)
    }
    expected_signatures = [
        _expected_relation_signature(relation)
        for relation in expected.get("relations", [])
    ]
    for expected_relation in expected.get("relations", []):
        signature = _expected_relation_signature(expected_relation)
        if any(_signature_matches(actual, signature) for actual in relations):
            stats["tp"] += 1
            continue
        stats["fn"] += 1
        # 위키링크의 방향이 모호할 수 있어 역방향 일치를 따로 센다.
        if any(
            _signature_matches(actual, _reversed_signature(signature))
            for actual in relations
        ):
            stats["reversed_only"] += 1
        errors.append(
            "missing relation: "
            f"{expected_relation['source_name']} -> "
            f"{expected_relation['target_name']} / "
            f"{expected_relation['relation_type']}"
        )
    forbidden_signatures = [
        _expected_relation_signature(relation)
        for relation in expected.get("forbidden_relations", [])
    ]
    forbidden_actual: set[tuple[str, str, str, str, str]] = set()
    for forbidden, signature in zip(
        expected.get("forbidden_relations", []),
        forbidden_signatures,
        strict=True,
    ):
        matches = {
            actual
            for actual in relations
            if _signature_matches(actual, signature)
            or _signature_matches(actual, _reversed_signature(signature))
        }
        if matches:
            forbidden_actual.update(matches)
            stats["forbidden_hit"] += 1
            errors.append(
                "forbidden relation: "
                f"{forbidden['source_name']} -> {forbidden['target_name']}"
            )
    expected_actual = {
        actual
        for actual in relations
        if any(_signature_matches(actual, wanted) for wanted in expected_signatures)
    }
    extras = relations - expected_actual - forbidden_actual
    stats["fp"] = len(forbidden_actual)
    if expected.get("judge_all_relations", False):
        stats["fp"] += len(extras)
        for extra in sorted(extras):
            errors.append(
                "unsupported relation: "
                f"{extra[1]} -> {extra[3]} / {extra[4]}"
            )
    else:
        stats["unjudged"] = len(extras)
    stats["unsupported_edge"] = stats["fp"]
    stats["judged"] = stats["tp"] + stats["fn"] + stats["fp"]
    if len(relations) > expected.get("max_relations", 10_000):
        errors.append(f"too many relations: {len(relations)}")

    for canonical in expected.get("canonical_matches", []):
        node = _node_for_expected(result, canonical)
        wanted_key = str(canonical["document_key"])
        if node is not None and getattr(node, "matched_existing_key", None) == wanted_key:
            stats["canonical_correct"] += 1
        else:
            errors.append(
                "canonical mismatch: "
                f"{canonical['kind']}:{canonical.get('name') or canonical.get('incoming_name')} "
                f"-> {wanted_key}"
            )

    for disposition in expected.get("dispositions", []):
        node = _node_for_expected(result, disposition)
        wanted = str(disposition["value"])
        actual, reason = (
            _node_disposition(result, kind=str(disposition["kind"]), node=node)
            if node is not None
            else ("missing", "")
        )
        if actual == wanted:
            stats["disposition_correct"] += 1
        else:
            errors.append(
                "node disposition: "
                f"{disposition['kind']}:{disposition.get('name')}={actual} != {wanted}"
            )
        reason_contains = str(disposition.get("reason_contains") or "")
        if disposition.get("reason_required") and not reason.strip():
            errors.append(
                "node disposition reason missing: "
                f"{disposition['kind']}:{disposition.get('name')}"
            )
        elif reason_contains and reason_contains not in reason:
            errors.append(
                "node disposition reason: "
                f"{disposition['kind']}:{disposition.get('name')} lacks {reason_contains}"
            )

    _score_relation_attributes(result, expected, errors=errors, stats=stats)
    if plan is not None:
        _score_plan(plan, expected, errors=errors, stats=stats)
    _score_relation_state(
        relation_state,
        expected,
        errors=errors,
        stats=stats,
    )
    return not errors, errors, stats


def _prompt_revision() -> str:
    """Git Commit과 분류 코드·Prompt Hash를 결합한 Prompt 버전을 반환한다."""
    completed = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    digest = hashlib.sha256()
    implementation_paths = sorted(
        (PROJECT_ROOT / "agent/wiki_builder/features").glob("*.py")
    )
    prompt_paths = sorted(
        (PROJECT_ROOT / "agent/prompts/templates").glob("personal_wiki*.md")
    )
    for path in [*implementation_paths, *prompt_paths]:
        digest.update(path.read_bytes())
    revision = completed.stdout.strip() if completed.returncode == 0 else "unknown"
    return f"{revision}+{digest.hexdigest()[:12]}"


def _format_ratio(correct: int, total: int) -> str:
    """분모가 없는 보조 지표는 N/A, 나머지는 건수와 비율로 표시한다."""
    if total == 0:
        return "N/A"
    return f"{correct}/{total} ({correct / total:.2%})"


def main() -> None:
    """전체 케이스를 실행하고 선별 없이 Markdown 결과 파일을 작성한다."""
    args = _args()
    cases = _load_cases()
    try:
        relation_states = _load_authoritative_relation_states(
            cases,
            args.relation_state_fixture,
        )
    except ValueError as error:
        raise SystemExit(f"관계 lifecycle 사전 검증 실패: {error}") from error
    estimated_input, estimated_output = _estimate_tokens(cases)
    estimate = _estimated_cost(
        estimated_input,
        estimated_output,
        input_cost_per_million=args.input_cost_per_million,
        output_cost_per_million=args.output_cost_per_million,
    )
    print(
        f"cases={len(cases)}, estimated_tokens={estimated_input}+{estimated_output}, "
        f"estimated_cost=${estimate:.6f}"
    )
    if not args.confirm_cost:
        raise SystemExit(
            "실제 호출하려면 예상 비용 확인 후 --confirm-cost를 추가하세요."
        )

    usage = Usage()

    def tracked_complete(system_prompt: str, user_prompt: str, model: str) -> str:
        """공유 LLM 경계로 호출하고 반환된 토큰 사용량을 누적한다."""
        completion = complete_with_usage(
            system_prompt,
            user_prompt,
            model=args.model,
            temperature=0,
        )
        usage.input_tokens += completion.input_tokens
        usage.output_tokens += completion.output_tokens
        return completion.text

    original_complete = classification.complete
    classification.complete = tracked_complete
    rows: list[dict[str, Any]] = []
    try:
        for case in cases:
            started = time.perf_counter()
            before_input = usage.input_tokens
            before_output = usage.output_tokens
            try:
                payload = case["input"]
                existing_entities = _existing_entries(
                    payload.get("existing_entities", []),
                    document_kind="entity",
                )
                existing_concepts = _existing_entries(
                    payload.get("existing_concepts", []),
                    document_kind="concept",
                )
                existing_relations = _existing_relations(
                    payload.get("existing_relations", [])
                )
                result, effective_model = classification.classify_wiki_source(
                    source_type=str(payload.get("source_type") or "web_clipping"),
                    source_metadata=dict(payload.get("source_metadata") or {}),
                    source_title=payload["title"],
                    source_content=payload["content"],
                    source_description=payload.get("description"),
                    source_tags=payload.get("tags", []),
                    existing_entities=existing_entities,
                    existing_concepts=existing_concepts,
                    model=args.model,
                )
                identity_draft = prepare_wiki_identity_resolution(
                    classification=result,
                    existing_entities=existing_entities,
                    existing_concepts=existing_concepts,
                )
                if identity_draft.conflicts:
                    raise ValueError(
                        "의미 identity 충돌은 wiki_identity_resolution 벤치에서 "
                        "별도로 평가해야 합니다."
                    )
                result = identity_draft.classification
                content = str(payload["content"])
                if str(payload.get("source_type") or "web_clipping") != "onboarding_seed":
                    result = link_wiki_relations(
                        source_title=str(payload["title"]),
                        source_content=content,
                        classification=result,
                        candidates_by_node=_relation_candidates(
                            result,
                            existing_entries=[
                                *existing_entities,
                                *existing_concepts,
                            ],
                            existing_relations=existing_relations,
                        ),
                        model=args.model,
                        completion=tracked_complete,
                    )
                plan = build_wiki_plan(
                    source_title=str(payload["title"]),
                    source_url=(
                        str(payload["source_url"])
                        if payload.get("source_url") is not None
                        else None
                    ),
                    source_tags=[str(tag) for tag in payload.get("tags", [])],
                    source_content_hash=hashlib.sha256(
                        content.encode("utf-8")
                    ).hexdigest(),
                    source_size_bytes=len(content.encode("utf-8")),
                    classification=result,
                    existing_entities=existing_entities,
                    existing_concepts=existing_concepts,
                    generated_at="2026-08-07T00:00:00+00:00",
                    model=effective_model,
                    existing_relations=existing_relations,
                )
                passed, errors, stats = _score(
                    result,
                    case["expected"],
                    plan=plan,
                    relation_state=(
                        relation_states.for_case(str(case["id"]))
                        if relation_states is not None
                        else None
                    ),
                )
            except Exception as error:
                passed = False
                errors = [f"{type(error).__name__}: {error}"]
                expected = case["expected"]
                stats = _empty_stats(expected)
                stats["fn"] = len(expected.get("relations", []))
            rows.append(
                {
                    "id": case["id"],
                    "passed": passed,
                    "errors": errors,
                    "stats": stats,
                    "latency": time.perf_counter() - started,
                    "input_tokens": usage.input_tokens - before_input,
                    "output_tokens": usage.output_tokens - before_output,
                }
            )
    finally:
        classification.complete = original_complete

    now = datetime.now(UTC)
    passed_count = sum(int(row["passed"]) for row in rows)
    total_latency = sum(float(row["latency"]) for row in rows)
    tp = sum(int(row["stats"]["tp"]) for row in rows)
    fn = sum(int(row["stats"]["fn"]) for row in rows)
    fp = sum(int(row["stats"]["fp"]) for row in rows)
    forbidden_hit = sum(int(row["stats"]["forbidden_hit"]) for row in rows)
    unsupported_edge = sum(
        int(row["stats"]["unsupported_edge"]) for row in rows
    )
    reversed_only = sum(int(row["stats"]["reversed_only"]) for row in rows)
    unjudged = sum(int(row["stats"]["unjudged"]) for row in rows)
    canonical_correct = sum(
        int(row["stats"]["canonical_correct"]) for row in rows
    )
    canonical_total = sum(int(row["stats"]["canonical_total"]) for row in rows)
    disposition_correct = sum(
        int(row["stats"]["disposition_correct"]) for row in rows
    )
    disposition_total = sum(
        int(row["stats"]["disposition_total"]) for row in rows
    )
    stale_correct = sum(int(row["stats"]["stale_correct"]) for row in rows)
    stale_total = sum(int(row["stats"]["stale_total"]) for row in rows)
    degree_correct = sum(int(row["stats"]["degree_correct"]) for row in rows)
    degree_total = sum(int(row["stats"]["degree_total"]) for row in rows)
    relation_attribute_correct = sum(
        int(row["stats"]["relation_attribute_correct"]) for row in rows
    )
    relation_attribute_total = sum(
        int(row["stats"]["relation_attribute_total"]) for row in rows
    )
    recall = tp / (tp + fn) if tp + fn else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    input_cost = usage.input_tokens * args.input_cost_per_million / 1_000_000
    output_cost = usage.output_tokens * args.output_cost_per_million / 1_000_000
    result_dir = ROOT / "results"
    result_dir.mkdir(exist_ok=True)
    safe_model = args.model.replace("/", "-")
    result_path = result_dir / f"{now.date().isoformat()}_{safe_model}.md"
    previous = sorted(
        path
        for path in result_dir.glob(f"*_{safe_model}.md")
        if path != result_path
    )
    lines = [
        "# Personal Wiki Builder Benchmark",
        "",
        f"- 실행 날짜: {now.isoformat()}",
        f"- 모델: {args.model}",
        f"- 프롬프트 버전: {_prompt_revision()}",
        "- 관계 lifecycle 상태: "
        + (
            f"{relation_states.source_path} "
            f"(sha256:{relation_states.sha256[:12]}, {_RELATION_STATE_PROVIDER})"
            if relation_states is not None
            else "요구 케이스 없음"
        ),
        f"- 케이스: {len(rows)}",
        f"- 성공: {passed_count}",
        f"- 정확도(케이스 전체 통과): {passed_count / len(rows):.2%}",
        f"- 연결 Recall: {recall:.2%} — 정답 연결 {tp}/{tp + fn}건 생성",
        f"- 연결 Precision(판정 가능 범위): {precision:.2%} — TP {tp}, FP {fp}",
        f"- Unsupported edge: {unsupported_edge}건 — 금지 관계 위반 {forbidden_hit}건",
        f"- 방향만 다른 일치: {reversed_only}건 (정답지와 반대 방향)",
        f"- 정답지 밖 연결: {unjudged}건 (판정 대상 아님)",
        f"- Canonical merge 정확도: {_format_ratio(canonical_correct, canonical_total)}",
        f"- Node disposition 정확도: {_format_ratio(disposition_correct, disposition_total)}",
        f"- Stale edge 처리 정확도: {_format_ratio(stale_correct, stale_total)}",
        f"- Degree 안정성: {_format_ratio(degree_correct, degree_total)}",
        "- 관계 provenance 필드 정확도: "
        f"{_format_ratio(relation_attribute_correct, relation_attribute_total)}",
        f"- 평균 지연시간: {total_latency / len(rows):.3f}s",
        f"- 입력 토큰: {usage.input_tokens}",
        f"- 출력 토큰: {usage.output_tokens}",
        f"- 실제 비용: ${input_cost + output_cost:.6f}",
        f"- 이전 결과 비교: {previous[-1].name if previous else '비교 대상 없음'}",
        "",
        "## 케이스별 결과",
        "",
        "| ID | 결과 | TP/FP/FN | 지연 | Input | Output | 실패 사유 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        reason = "; ".join(row["errors"]).replace("|", "\\|")
        lines.append(
            f"| {row['id']} | {'PASS' if row['passed'] else 'FAIL'} | "
            f"{row['stats']['tp']}/{row['stats']['fp']}/{row['stats']['fn']} | "
            f"{row['latency']:.3f}s | {row['input_tokens']} | "
            f"{row['output_tokens']} | {reason} |"
        )
    result_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(result_path)


if __name__ == "__main__":
    main()
