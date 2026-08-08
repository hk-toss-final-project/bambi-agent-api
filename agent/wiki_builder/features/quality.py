"""개인 Wiki 문서와 관계의 결정적 품질 검증.

LLM이나 DB를 호출하지 않고 현재 Wiki Snapshot의 중복 표면형, 고아 문서,
관계 근거·수명주기, 모순 Metadata와 과밀 Hub를 검사한다. 검증 결과는
운영 Lint와 Build 품질 Gate가 함께 사용할 수 있는 구조화된 보고서로 반환한다.
"""

from __future__ import annotations

import math
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent.wiki_builder.models import ExistingWikiEntry, WikiRelationPlan


ALLOWED_WIKI_RELATION_TYPES = frozenset(
    {
        "entity_relation",
        "applies_concept",
        "related_concept",
        "alias_of",
        "instance_of",
        "subtopic_of",
        "part_of",
        "located_in",
        "occurs_in",
        "affects",
        "causes",
        "associated_with",
    }
)
_RELATION_KIND_PAIRS: dict[str, frozenset[tuple[str, str]]] = {
    "entity_relation": frozenset({("entity", "entity")}),
    "applies_concept": frozenset({("entity", "concept")}),
    "related_concept": frozenset({("concept", "concept")}),
    "alias_of": frozenset({("entity", "entity"), ("concept", "concept")}),
    "instance_of": frozenset(
        {("entity", "concept"), ("concept", "concept")}
    ),
    "subtopic_of": frozenset({("concept", "concept")}),
    "part_of": frozenset(
        {
            ("entity", "entity"),
            ("entity", "concept"),
            ("concept", "concept"),
        }
    ),
    "located_in": frozenset({("entity", "entity")}),
    "occurs_in": frozenset({("entity", "entity")}),
    "affects": frozenset(
        {
            ("entity", "entity"),
            ("entity", "concept"),
            ("concept", "entity"),
            ("concept", "concept"),
        }
    ),
    "causes": frozenset(
        {
            ("entity", "entity"),
            ("entity", "concept"),
            ("concept", "entity"),
            ("concept", "concept"),
        }
    ),
    "associated_with": frozenset(
        {
            ("entity", "entity"),
            ("entity", "concept"),
            ("concept", "entity"),
            ("concept", "concept"),
        }
    ),
}
_ALLOWED_PROVENANCE_KINDS = frozenset(
    {"source_explicit", "semantic_inference", "user_declared", "system_rule"}
)
_PROVENANCE_CONFIDENCE_FLOORS = {
    "source_explicit": 0.70,
    "semantic_inference": 0.78,
    "user_declared": 0.90,
    "system_rule": 0.90,
}
_ALLOWED_REVIEW_STATUSES = frozenset({"unreviewed", "accepted", "rejected"})
_ALLOWED_RELATION_STATUSES = frozenset({"active", "superseded"})
_ALLOWED_CONTRADICTION_SEVERITIES = frozenset({"warning", "conflict", "error"})
_SEVERITY_ORDER = {"error": 0, "warning": 1}


@dataclass(frozen=True, slots=True)
class WikiQualityIssue:
    """Wiki 품질 검증에서 발견한 한 가지 문제."""

    code: str
    severity: str
    message: str
    document_keys: tuple[str, ...] = ()
    relation_signature: tuple[str, str, str, str, str] | None = None
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WikiQualityReport:
    """결정적 Wiki 품질 검증의 통과 여부, 문제와 집계 지표."""

    passed: bool
    issues: tuple[WikiQualityIssue, ...]
    metrics: Mapping[str, int | float]

    def issues_for(self, code: str) -> tuple[WikiQualityIssue, ...]:
        """지정한 안정적 문제 코드에 해당하는 항목만 반환한다."""
        return tuple(issue for issue in self.issues if issue.code == code)


def _document_identity(entry: ExistingWikiEntry) -> str:
    """문서 종류와 Key를 합쳐 Namespace 안에서 구분되는 식별자를 만든다."""
    return f"{entry.document_kind}:{entry.document_key}"


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


def _normalize_surface(value: str) -> str:
    """Unicode·대소문자·공백·구두점 차이를 제거한 비교 표면형을 만든다."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _metadata_strings(metadata: Mapping[str, object], key: str) -> tuple[str, ...]:
    """Metadata 배열에서 비어 있지 않은 문자열만 안전하게 읽는다."""
    value = metadata.get(key)
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    return tuple(
        normalized
        for item in value
        if (normalized := str(item).strip())
    )


def _relation_confidence(metadata: Mapping[str, object]) -> float | None:
    """관계 신뢰도를 숫자로 읽고 잘못된 값은 None으로 반환한다."""
    value = metadata.get("confidence", 1.0)
    if isinstance(value, bool):
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return confidence if math.isfinite(confidence) and 0.0 <= confidence <= 1.0 else None


def _has_relation_support(metadata: Mapping[str, object]) -> bool:
    """관계 Metadata에 인용·출처·사용자 선언·규칙 중 하나가 있는지 확인한다."""
    scalar_keys = (
        "evidence",
        "quote",
        "source_excerpt",
        "source_document_version_id",
        "source_version_id",
        "source_id",
        "user_signal_id",
        "rule_key",
    )
    if any(str(metadata.get(key) or "").strip() for key in scalar_keys):
        return True
    sequence_keys = ("source_ids", "sources", "support_ids")
    return any(_metadata_strings(metadata, key) for key in sequence_keys)


def _add_issue(
    issues: list[WikiQualityIssue],
    *,
    code: str,
    severity: str,
    message: str,
    document_keys: tuple[str, ...] = (),
    relation_signature: tuple[str, str, str, str, str] | None = None,
    details: Mapping[str, object] | None = None,
) -> None:
    """품질 문제를 동일한 구조로 누적한다."""
    issues.append(
        WikiQualityIssue(
            code=code,
            severity=severity,
            message=message,
            document_keys=document_keys,
            relation_signature=relation_signature,
            details=details or {},
        )
    )


def _validate_contradictions(
    entry: ExistingWikiEntry,
    issues: list[WikiQualityIssue],
) -> int:
    """문서의 contradictions Metadata 구조와 심각도를 검증한다."""
    raw = entry.metadata.get("contradictions")
    if raw is None:
        raw = entry.metadata.get("contradiction")
    if raw is None:
        return 0
    document_id = _document_identity(entry)
    if isinstance(raw, Mapping):
        items: Sequence[object] = (raw,)
    elif isinstance(raw, (list, tuple)):
        items = raw
    else:
        _add_issue(
            issues,
            code="invalid_contradiction_metadata",
            severity="error",
            message=f"{document_id}의 모순 Metadata가 객체 또는 배열이 아닙니다.",
            document_keys=(document_id,),
        )
        return 0

    contradiction_count = 0
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            _add_issue(
                issues,
                code="invalid_contradiction_metadata",
                severity="error",
                message=f"{document_id}의 모순 {index + 1}번 항목이 객체가 아닙니다.",
                document_keys=(document_id,),
                details={"index": index},
            )
            continue
        severity = str(item.get("severity") or "warning").strip().lower()
        if severity not in _ALLOWED_CONTRADICTION_SEVERITIES:
            _add_issue(
                issues,
                code="invalid_contradiction_metadata",
                severity="error",
                message=f"{document_id}의 모순 심각도 '{severity}'를 사용할 수 없습니다.",
                document_keys=(document_id,),
                details={"index": index, "severity": severity},
            )
            continue
        contradiction_count += 1
        description = str(
            item.get("message")
            or item.get("description")
            or item.get("statement")
            or "상충하는 지식이 기록되어 있습니다."
        ).strip()
        _add_issue(
            issues,
            code="contradiction",
            severity="warning" if severity == "warning" else "error",
            message=f"{document_id}: {description}",
            document_keys=(document_id,),
            details={"index": index, "contradiction_severity": severity},
        )
    return contradiction_count


def _validate_policy(
    *,
    low_confidence_threshold: float,
    dense_hub_min_degree: int,
    dense_hub_ratio: float,
) -> None:
    """Wiki 품질 검증 임계값이 유효한 범위인지 확인한다."""
    if not 0.0 <= low_confidence_threshold <= 1.0:
        raise ValueError("low_confidence_threshold는 0과 1 사이여야 합니다.")
    if dense_hub_min_degree < 1:
        raise ValueError("dense_hub_min_degree는 1 이상이어야 합니다.")
    if not 0.0 < dense_hub_ratio <= 1.0:
        raise ValueError("dense_hub_ratio는 0보다 크고 1 이하여야 합니다.")


def validate_wiki_quality(
    entries: Sequence[ExistingWikiEntry],
    relations: Sequence[WikiRelationPlan],
    *,
    low_confidence_threshold: float = 0.70,
    dense_hub_min_degree: int = 8,
    dense_hub_ratio: float = 0.6,
) -> WikiQualityReport:
    """현재 Wiki Snapshot의 문서와 관계 품질을 결정적으로 검증한다.

    고아 문서는 명세대로 검증된 인바운드 관계가 없는 문서로 계산한다. 관계가
    단순히 존재한다는 이유로 문제를 가리지 않도록, 허용 Ontology·근거·신뢰도·
    검토 상태·수명주기를 모두 통과한 관계만 연결도와 Hub 계산에 사용한다.
    """
    _validate_policy(
        low_confidence_threshold=low_confidence_threshold,
        dense_hub_min_degree=dense_hub_min_degree,
        dense_hub_ratio=dense_hub_ratio,
    )
    issues: list[WikiQualityIssue] = []
    sorted_entries = sorted(
        entries,
        key=lambda entry: (
            entry.document_kind,
            entry.document_key,
            entry.title.casefold(),
        ),
    )
    sorted_relations = sorted(relations, key=_relation_signature)

    entries_by_id: dict[str, ExistingWikiEntry] = {}
    duplicate_document_count = 0
    surfaces: defaultdict[str, set[str]] = defaultdict(set)
    display_surface: dict[str, str] = {}
    contradiction_count = 0

    for entry in sorted_entries:
        document_id = _document_identity(entry)
        if entry.document_kind not in {"entity", "concept"}:
            _add_issue(
                issues,
                code="invalid_document_kind",
                severity="error",
                message=f"{document_id}의 문서 종류를 사용할 수 없습니다.",
                document_keys=(document_id,),
            )
        if document_id in entries_by_id:
            duplicate_document_count += 1
            _add_issue(
                issues,
                code="duplicate_document",
                severity="error",
                message=f"문서 식별자 {document_id}가 중복되었습니다.",
                document_keys=(document_id,),
            )
        else:
            entries_by_id[document_id] = entry

        for surface in (entry.title, *_metadata_strings(entry.metadata, "aliases")):
            normalized = _normalize_surface(surface)
            if not normalized:
                continue
            surfaces[normalized].add(document_id)
            display_surface.setdefault(normalized, surface.strip())
        contradiction_count += _validate_contradictions(entry, issues)

    duplicate_surface_count = 0
    for normalized, document_ids in sorted(surfaces.items()):
        if len(document_ids) < 2:
            continue
        duplicate_surface_count += 1
        identities = tuple(sorted(document_ids))
        _add_issue(
            issues,
            code="duplicate_surface",
            severity="error",
            message=(
                f"표면형 '{display_surface[normalized]}'이 여러 canonical 문서에 "
                "등록되어 있습니다."
            ),
            document_keys=identities,
            details={"normalized_surface": normalized},
        )

    seen_relations: set[tuple[str, str, str, str, str]] = set()
    verified_relations: list[WikiRelationPlan] = []
    relation_issue_counts: defaultdict[str, int] = defaultdict(int)

    for relation in sorted_relations:
        signature = _relation_signature(relation)
        source_id = f"{relation.source_document_kind}:{relation.source_document_key}"
        target_id = f"{relation.target_document_kind}:{relation.target_document_key}"
        metadata = relation.metadata
        valid = True

        if signature in seen_relations:
            relation_issue_counts["duplicate_relation"] += 1
            _add_issue(
                issues,
                code="duplicate_relation",
                severity="error",
                message="동일한 Wiki 관계가 중복되었습니다.",
                document_keys=(source_id, target_id),
                relation_signature=signature,
            )
            valid = False
        else:
            seen_relations.add(signature)

        if source_id == target_id:
            relation_issue_counts["self_relation"] += 1
            _add_issue(
                issues,
                code="self_relation",
                severity="error",
                message=f"{source_id}가 자기 자신을 가리킵니다.",
                document_keys=(source_id,),
                relation_signature=signature,
            )
            valid = False

        missing_endpoints = tuple(
            identity
            for identity in (source_id, target_id)
            if identity not in entries_by_id
        )
        if missing_endpoints:
            relation_issue_counts["missing_relation_endpoint"] += 1
            _add_issue(
                issues,
                code="missing_relation_endpoint",
                severity="error",
                message="관계가 현재 Wiki에 없는 문서를 참조합니다.",
                document_keys=missing_endpoints,
                relation_signature=signature,
            )
            valid = False

        if relation.relation_type not in ALLOWED_WIKI_RELATION_TYPES:
            relation_issue_counts["unsupported_relation_type"] += 1
            _add_issue(
                issues,
                code="unsupported_relation_type",
                severity="error",
                message=f"관계 유형 '{relation.relation_type}'을 사용할 수 없습니다.",
                document_keys=(source_id, target_id),
                relation_signature=signature,
            )
            valid = False
        elif (
            relation.source_document_kind,
            relation.target_document_kind,
        ) not in _RELATION_KIND_PAIRS[relation.relation_type]:
            relation_issue_counts["invalid_relation_kind_pair"] += 1
            _add_issue(
                issues,
                code="invalid_relation_kind_pair",
                severity="error",
                message=(
                    f"{relation.relation_type}에 "
                    f"{relation.source_document_kind}->{relation.target_document_kind} "
                    "조합을 사용할 수 없습니다."
                ),
                document_keys=(source_id, target_id),
                relation_signature=signature,
            )
            valid = False

        status = str(metadata.get("status", "active")).strip().lower()
        if status not in _ALLOWED_RELATION_STATUSES:
            relation_issue_counts["invalid_relation_status"] += 1
            _add_issue(
                issues,
                code="invalid_relation_status",
                severity="error",
                message=f"관계 상태 '{status}'를 사용할 수 없습니다.",
                document_keys=(source_id, target_id),
                relation_signature=signature,
            )
            valid = False
        elif status == "superseded":
            relation_issue_counts["superseded_relation"] += 1
            _add_issue(
                issues,
                code="superseded_relation",
                severity="error",
                message="대체된 관계가 현재 Wiki Snapshot에 포함되어 있습니다.",
                document_keys=(source_id, target_id),
                relation_signature=signature,
            )
            valid = False

        review_status = str(metadata.get("review_status", "unreviewed")).strip().lower()
        if review_status not in _ALLOWED_REVIEW_STATUSES:
            relation_issue_counts["invalid_review_status"] += 1
            _add_issue(
                issues,
                code="invalid_review_status",
                severity="error",
                message=f"관계 검토 상태 '{review_status}'를 사용할 수 없습니다.",
                document_keys=(source_id, target_id),
                relation_signature=signature,
            )
            valid = False
        elif review_status == "rejected":
            relation_issue_counts["rejected_relation"] += 1
            _add_issue(
                issues,
                code="rejected_relation",
                severity="error",
                message="거절된 관계가 현재 Wiki Snapshot에 포함되어 있습니다.",
                document_keys=(source_id, target_id),
                relation_signature=signature,
            )
            valid = False
        elif review_status == "unreviewed":
            relation_issue_counts["unreviewed_relation"] += 1
            _add_issue(
                issues,
                code="unreviewed_relation",
                severity="warning",
                message="아직 검토되지 않은 관계입니다.",
                document_keys=(source_id, target_id),
                relation_signature=signature,
            )
            valid = False

        provenance_kind = str(
            metadata.get("provenance_kind", "source_explicit")
        ).strip()
        confidence = _relation_confidence(metadata)
        if confidence is None:
            relation_issue_counts["invalid_relation_confidence"] += 1
            _add_issue(
                issues,
                code="invalid_relation_confidence",
                severity="error",
                message="관계 신뢰도가 0과 1 사이의 유한한 숫자가 아닙니다.",
                document_keys=(source_id, target_id),
                relation_signature=signature,
            )
            valid = False
        else:
            confidence_threshold = max(
                low_confidence_threshold,
                _PROVENANCE_CONFIDENCE_FLOORS.get(provenance_kind, 1.0),
            )
        if confidence is not None and confidence < confidence_threshold:
            relation_issue_counts["low_confidence_relation"] += 1
            _add_issue(
                issues,
                code="low_confidence_relation",
                severity="error",
                message=(
                    f"관계 신뢰도 {confidence:.3f}가 임계값 "
                    f"{confidence_threshold:.3f}보다 낮습니다."
                ),
                document_keys=(source_id, target_id),
                relation_signature=signature,
                details={"confidence": confidence},
            )
            valid = False

        if provenance_kind not in _ALLOWED_PROVENANCE_KINDS:
            relation_issue_counts["invalid_provenance_kind"] += 1
            _add_issue(
                issues,
                code="invalid_provenance_kind",
                severity="error",
                message=f"관계 근거 유형 '{provenance_kind}'을 사용할 수 없습니다.",
                document_keys=(source_id, target_id),
                relation_signature=signature,
            )
            valid = False

        if not _has_relation_support(metadata):
            relation_issue_counts["source_less_relation"] += 1
            _add_issue(
                issues,
                code="source_less_relation",
                severity="error",
                message="인용·출처·사용자 선언·규칙 근거가 없는 관계입니다.",
                document_keys=(source_id, target_id),
                relation_signature=signature,
            )
            valid = False

        if valid:
            verified_relations.append(relation)

    inbound: defaultdict[str, int] = defaultdict(int)
    neighbors: defaultdict[str, set[str]] = defaultdict(set)
    for relation in verified_relations:
        source_id = f"{relation.source_document_kind}:{relation.source_document_key}"
        target_id = f"{relation.target_document_kind}:{relation.target_document_key}"
        inbound[target_id] += 1
        neighbors[source_id].add(target_id)
        neighbors[target_id].add(source_id)

    orphan_count = 0
    for document_id in sorted(entries_by_id):
        if inbound[document_id] > 0:
            continue
        orphan_count += 1
        _add_issue(
            issues,
            code="orphan_document",
            severity="warning",
            message=f"{document_id}에 검증된 인바운드 관계가 없습니다.",
            document_keys=(document_id,),
        )

    dense_hub_count = 0
    node_count = len(entries_by_id)
    possible_neighbors = max(node_count - 1, 1)
    for document_id in sorted(entries_by_id):
        degree = len(neighbors[document_id])
        ratio = degree / possible_neighbors
        if degree < dense_hub_min_degree or ratio < dense_hub_ratio:
            continue
        dense_hub_count += 1
        _add_issue(
            issues,
            code="dense_hub",
            severity="warning",
            message=(
                f"{document_id}가 {degree}개 문서와 연결되어 전체 이웃의 "
                f"{ratio:.1%}를 차지합니다."
            ),
            document_keys=(document_id,),
            details={"degree": degree, "neighbor_ratio": ratio},
        )

    issues.sort(
        key=lambda issue: (
            _SEVERITY_ORDER.get(issue.severity, 2),
            issue.code,
            issue.document_keys,
            issue.relation_signature or ("", "", "", "", ""),
            issue.message,
        )
    )
    error_count = sum(issue.severity == "error" for issue in issues)
    warning_count = sum(issue.severity == "warning" for issue in issues)
    metrics: dict[str, int | float] = {
        "document_count": len(entries_by_id),
        "relation_count": len(relations),
        "verified_relation_count": len(verified_relations),
        "issue_count": len(issues),
        "error_count": error_count,
        "warning_count": warning_count,
        "orphan_count": orphan_count,
        "duplicate_document_count": duplicate_document_count,
        "duplicate_surface_count": duplicate_surface_count,
        "unsupported_relation_count": relation_issue_counts[
            "unsupported_relation_type"
        ],
        "low_confidence_relation_count": relation_issue_counts[
            "low_confidence_relation"
        ],
        "rejected_relation_count": relation_issue_counts["rejected_relation"],
        "source_less_relation_count": relation_issue_counts[
            "source_less_relation"
        ],
        "superseded_relation_count": relation_issue_counts[
            "superseded_relation"
        ],
        "contradiction_count": contradiction_count,
        "dense_hub_count": dense_hub_count,
    }
    return WikiQualityReport(
        passed=error_count == 0,
        issues=tuple(issues),
        metrics=metrics,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wba_014(
    entries: Sequence[ExistingWikiEntry],
    relations: Sequence[WikiRelationPlan],
    *,
    low_confidence_threshold: float = 0.70,
    dense_hub_min_degree: int = 8,
    dense_hub_ratio: float = 0.6,
) -> WikiQualityReport:
    """[WBA-014] Wiki 품질 검증.

    중복, 누락, 잘못된 분류와 신뢰할 수 없는 관계를 검사한다.
    """
    return validate_wiki_quality(
        entries,
        relations,
        low_confidence_threshold=low_confidence_threshold,
        dense_hub_min_degree=dense_hub_min_degree,
        dense_hub_ratio=dense_hub_ratio,
    )
