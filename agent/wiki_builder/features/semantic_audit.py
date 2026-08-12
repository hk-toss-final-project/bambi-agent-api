"""Personal Wiki V3의 LLM 의미 감사와 결정적 응답 검증을 수행한다.

LLM은 모순·오래된 주장·누락 주제·누락 관계·지식 공백 후보를 제안한다. 이
모듈은 안정적인 Page·Source·후보 참조, 원문 인용, confidence와 허용 Ontology를
다시 검증해 후속 유지 그래프가 사용할 구조화된 보고서만 반환한다.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from agent.llm.api import complete, strip_json_fence
from agent.wiki_builder.features.identity_resolution import normalize_wiki_surface
from agent.wiki_builder.features.quality import ALLOWED_WIKI_RELATION_TYPES
from agent.wiki_builder.features.relation_candidates import WikiNodeIdentity
from agent.wiki_builder.features.semantic_lint import (
    WikiSemanticLintContext,
    candidate_by_reference,
    iter_context_surfaces,
    page_by_reference,
    source_by_reference,
)

type WikiSemanticCompletion = Callable[..., str]

SEMANTIC_LINT_PROMPT_VERSION = "personal-wiki-semantic-lint-v1"
_PROMPT_PATH = (
    Path(__file__).parents[2]
    / "prompts"
    / "templates"
    / "personal_wiki_semantic_lint.md"
)
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()
_ALLOWED_SEVERITIES = frozenset({"warning", "error"})
_ALLOWED_PROVENANCE_KINDS = frozenset({"source_explicit", "semantic_inference"})
_ALLOWED_RELATION_DIRECTIONS = frozenset({"topic_to_page", "page_to_topic"})
_CODE_CONFIDENCE_FLOORS = {
    "contradiction": 0.78,
    "stale_claim": 0.85,
    "missing_topic": 0.82,
    "missing_relation": 0.80,
    "knowledge_gap": 0.80,
}
_PROVENANCE_CONFIDENCE_FLOORS = {
    "source_explicit": 0.70,
    "semantic_inference": 0.78,
}


class WikiSemanticIssueCode(StrEnum):
    """V3 의미 감사가 후속 유지 계획에 전달할 수 있는 문제 코드."""

    CONTRADICTION = "contradiction"
    STALE_CLAIM = "stale_claim"
    MISSING_TOPIC = "missing_topic"
    MISSING_RELATION = "missing_relation"
    KNOWLEDGE_GAP = "knowledge_gap"


@dataclass(frozen=True, slots=True)
class WikiSemanticEvidence:
    """활성 Source 참조와 그 안에서 검증된 연속 인용 한 건."""

    source_reference: str
    quote: str


@dataclass(frozen=True, slots=True)
class WikiMissingTopicProposal:
    """근거 Source에서 새 canonical Page를 만들기 위한 제안."""

    document_kind: str
    title: str
    summary: str
    aliases: tuple[str, ...]
    related_page_reference: str | None = None
    relation_type: str | None = None
    relation_direction: str | None = None


@dataclass(frozen=True, slots=True)
class WikiMissingRelationProposal:
    """전역 후보의 두 기존 Page 사이에 추가할 검증 관계 제안."""

    source_page_reference: str
    target_page_reference: str
    relation_type: str
    evidence_source_reference: str
    evidence: str
    provenance_kind: str
    confidence: float
    rationale: str


@dataclass(frozen=True, slots=True)
class WikiSemanticIssue:
    """결정적 검증을 통과한 의미 유지보수 문제 한 건."""

    issue_id: str
    code: WikiSemanticIssueCode
    severity: str
    title: str
    rationale: str
    confidence: float
    page_references: tuple[str, ...]
    source_references: tuple[str, ...]
    evidence: tuple[WikiSemanticEvidence, ...]
    candidate_reference: str | None = None
    topic: WikiMissingTopicProposal | None = None
    relation: WikiMissingRelationProposal | None = None
    research_query: str | None = None


@dataclass(frozen=True, slots=True)
class WikiSemanticLintReport:
    """V3 의미 감사 문제·경고·집계와 실행 Model 추적."""

    issues: tuple[WikiSemanticIssue, ...]
    warnings: tuple[str, ...]
    metrics: Mapping[str, int | float]
    model: str
    prompt_version: str = SEMANTIC_LINT_PROMPT_VERSION

    def issues_for(
        self,
        code: WikiSemanticIssueCode | str,
    ) -> tuple[WikiSemanticIssue, ...]:
        """지정한 문제 코드에 해당하는 항목만 반환한다."""
        expected = str(code)
        return tuple(issue for issue in self.issues if issue.code.value == expected)


def _as_list(value: object) -> list[object]:
    """JSON 배열이 아니면 빈 목록으로 정규화한다."""
    return list(value) if isinstance(value, list) else []


def _unique_known_references(
    value: object,
    *,
    known: Mapping[str, object],
) -> tuple[str, ...] | None:
    """중복 없는 참조 배열을 읽고 허구 참조가 있으면 None을 반환한다."""
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for raw in value:
        reference = str(raw).strip()
        if not reference or reference not in known:
            return None
        if reference not in result:
            result.append(reference)
    return tuple(result)


def _confidence(value: object) -> float | None:
    """LLM confidence를 0과 1 사이 숫자로 읽는다."""
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0.0 <= parsed <= 1.0 else None


def _quote_exists(quote: str, source_content: str) -> bool:
    """연속 공백과 줄바꿈 차이를 허용해 인용이 실제 원문에 있는지 확인한다."""
    if quote in source_content:
        return True
    normalized_quote = " ".join(quote.split())
    normalized_source = " ".join(source_content.split())
    return bool(normalized_quote) and normalized_quote in normalized_source


def _parse_evidence(
    value: object,
    *,
    known_sources: Mapping[str, object],
) -> tuple[WikiSemanticEvidence, ...] | None:
    """Source 참조와 원문 일치를 검증한 인용 목록을 만든다."""
    result: list[WikiSemanticEvidence] = []
    for raw in _as_list(value):
        if not isinstance(raw, Mapping):
            return None
        source_reference = str(raw.get("source_ref") or "").strip()
        quote = str(raw.get("quote") or "").strip()
        source = known_sources.get(source_reference)
        content = str(getattr(source, "content", ""))
        if not source_reference or source is None or not _quote_exists(quote, content):
            return None
        item = WikiSemanticEvidence(source_reference, quote)
        if item not in result:
            result.append(item)
    return tuple(result)


def _parse_topic(
    value: object,
    *,
    context: WikiSemanticLintContext,
) -> WikiMissingTopicProposal | None:
    """기존 표면형과 겹치지 않는 누락 Page 제안을 검증한다."""
    if not isinstance(value, Mapping):
        return None
    document_kind = str(value.get("document_kind") or "").strip()
    title = str(value.get("title") or "").strip()
    summary = str(value.get("summary") or "").strip()
    if document_kind not in {"entity", "concept"} or not title or not summary:
        return None
    existing_surfaces = {
        normalize_wiki_surface(surface) for surface in iter_context_surfaces(context)
    }
    if normalize_wiki_surface(title) in existing_surfaces:
        return None
    aliases = tuple(
        dict.fromkeys(
            alias
            for raw in _as_list(value.get("aliases"))
            if (alias := str(raw).strip())
            and normalize_wiki_surface(alias) not in existing_surfaces
        )
    )
    related_page_reference = str(value.get("related_page_ref") or "").strip() or None
    relation_type = str(value.get("relation_type") or "").strip() or None
    relation_direction = str(value.get("relation_direction") or "").strip() or None
    if related_page_reference is not None and related_page_reference not in page_by_reference(
        context
    ):
        return None
    relation_values = (related_page_reference, relation_type, relation_direction)
    if any(relation_values) and not all(relation_values):
        return None
    if relation_type is not None and relation_type not in ALLOWED_WIKI_RELATION_TYPES:
        return None
    if (
        relation_direction is not None
        and relation_direction not in _ALLOWED_RELATION_DIRECTIONS
    ):
        return None
    return WikiMissingTopicProposal(
        document_kind=document_kind,
        title=title,
        summary=summary,
        aliases=aliases,
        related_page_reference=related_page_reference,
        relation_type=relation_type,
        relation_direction=relation_direction,
    )


def _parse_relation(
    value: object,
    *,
    context: WikiSemanticLintContext,
    candidate_reference: str,
) -> WikiMissingRelationProposal | None:
    """전역 후보 endpoint와 원문 근거에 맞는 누락 관계 제안을 검증한다."""
    if not isinstance(value, Mapping):
        return None
    candidate = candidate_by_reference(context).get(candidate_reference)
    if candidate is None:
        return None
    source_page_reference = str(value.get("source_page_ref") or "").strip()
    target_page_reference = str(value.get("target_page_ref") or "").strip()
    if {
        source_page_reference,
        target_page_reference,
    } != {
        candidate.source_page_reference,
        candidate.target_page_reference,
    }:
        return None
    relation_type = str(value.get("relation_type") or "").strip()
    provenance_kind = str(value.get("provenance_kind") or "").strip()
    confidence = _confidence(value.get("confidence"))
    rationale = str(value.get("rationale") or "").strip()
    if relation_type not in ALLOWED_WIKI_RELATION_TYPES:
        return None
    if provenance_kind not in _ALLOWED_PROVENANCE_KINDS or confidence is None:
        return None
    if confidence < _PROVENANCE_CONFIDENCE_FLOORS[provenance_kind]:
        return None
    if provenance_kind == "semantic_inference" and not rationale:
        return None
    evidence_source_reference = str(
        value.get("evidence_source_ref") or ""
    ).strip()
    evidence = str(value.get("evidence") or "").strip()
    source = source_by_reference(context).get(evidence_source_reference)
    if source is None or not _quote_exists(evidence, source.content):
        return None
    return WikiMissingRelationProposal(
        source_page_reference=source_page_reference,
        target_page_reference=target_page_reference,
        relation_type=relation_type,
        evidence_source_reference=evidence_source_reference,
        evidence=evidence,
        provenance_kind=provenance_kind,
        confidence=confidence,
        rationale=rationale,
    )


def _issue_id(
    *,
    code: WikiSemanticIssueCode,
    page_references: Sequence[str],
    source_references: Sequence[str],
    candidate_reference: str | None,
    topic: WikiMissingTopicProposal | None,
    research_query: str | None,
) -> str:
    """재실행에서도 같은 문제에 같은 멱등 식별자를 부여한다."""
    payload = {
        "code": code.value,
        "pages": sorted(page_references),
        "sources": sorted(source_references),
        "candidate": candidate_reference,
        "topic": (
            [topic.document_kind, normalize_wiki_surface(topic.title)]
            if topic is not None
            else None
        ),
        "query": normalize_wiki_surface(research_query or ""),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"semantic-{digest[:20]}"


def _parse_issue(
    raw: object,
    *,
    context: WikiSemanticLintContext,
) -> tuple[WikiSemanticIssue | None, str | None]:
    """LLM 문제 한 건을 코드별 계약으로 검증하고 거절 사유를 요약한다."""
    if not isinstance(raw, Mapping):
        return None, "issue가 JSON 객체가 아닙니다."
    raw_code = str(raw.get("code") or "").strip()
    try:
        code = WikiSemanticIssueCode(raw_code)
    except ValueError:
        return None, f"지원하지 않는 issue code입니다: {raw_code or '(없음)'}"
    severity = str(raw.get("severity") or "warning").strip()
    if severity not in _ALLOWED_SEVERITIES:
        return None, f"지원하지 않는 severity입니다: {severity}"
    confidence = _confidence(raw.get("confidence"))
    if confidence is None or confidence < _CODE_CONFIDENCE_FLOORS[code.value]:
        return None, f"{code.value} confidence가 기준보다 낮습니다."
    pages = page_by_reference(context)
    sources = source_by_reference(context)
    page_references = _unique_known_references(raw.get("page_refs"), known=pages)
    source_references = _unique_known_references(
        raw.get("source_refs"),
        known=sources,
    )
    if page_references is None or source_references is None:
        return None, f"{code.value}가 존재하지 않는 참조를 사용합니다."
    evidence = _parse_evidence(raw.get("evidence"), known_sources=sources)
    if evidence is None:
        return None, f"{code.value}의 evidence가 활성 Source 원문과 다릅니다."
    evidence_source_references = {item.source_reference for item in evidence}
    if not evidence_source_references.issubset(set(source_references)):
        return None, f"{code.value} evidence Source가 source_refs에 없습니다."
    if code in {
        WikiSemanticIssueCode.CONTRADICTION,
        WikiSemanticIssueCode.STALE_CLAIM,
    } and (len(evidence) < 2 or len(evidence_source_references) < 2):
        return None, f"{code.value}에는 서로 다른 Source 근거가 2개 이상 필요합니다."

    candidate_reference = str(raw.get("candidate_ref") or "").strip() or None
    topic: WikiMissingTopicProposal | None = None
    relation: WikiMissingRelationProposal | None = None
    research_query: str | None = None
    if code is WikiSemanticIssueCode.MISSING_TOPIC:
        topic = _parse_topic(raw.get("topic"), context=context)
        if topic is None or not evidence:
            return None, "missing_topic의 새 Page 또는 원문 근거가 유효하지 않습니다."
    elif code is WikiSemanticIssueCode.MISSING_RELATION:
        if candidate_reference is None:
            return None, "missing_relation에 candidate_ref가 없습니다."
        relation = _parse_relation(
            raw.get("relation"),
            context=context,
            candidate_reference=candidate_reference,
        )
        if relation is None:
            return None, "missing_relation 제안이 후보 endpoint 또는 원문과 다릅니다."
    elif code is WikiSemanticIssueCode.KNOWLEDGE_GAP:
        research_query = " ".join(
            str(raw.get("research_query") or "").split()
        )[:200]
        if not research_query or not (page_references or source_references):
            return None, "knowledge_gap에 근거 범위 또는 검색 질의가 없습니다."

    title = str(raw.get("title") or code.value).strip()[:160]
    rationale = str(raw.get("rationale") or "").strip()[:1_000]
    if not rationale:
        return None, f"{code.value}에 판정 근거가 없습니다."
    return (
        WikiSemanticIssue(
            issue_id=_issue_id(
                code=code,
                page_references=page_references,
                source_references=source_references,
                candidate_reference=candidate_reference,
                topic=topic,
                research_query=research_query,
            ),
            code=code,
            severity=severity,
            title=title,
            rationale=rationale,
            confidence=confidence,
            page_references=page_references,
            source_references=source_references,
            evidence=evidence,
            candidate_reference=candidate_reference,
            topic=topic,
            relation=relation,
            research_query=research_query,
        ),
        None,
    )


def _report(
    issues: Sequence[WikiSemanticIssue],
    warnings: Sequence[str],
    *,
    model: str,
) -> WikiSemanticLintReport:
    """검증 문제와 경고를 안정적으로 정렬하고 코드별 지표를 만든다."""
    sorted_issues = tuple(
        sorted(issues, key=lambda issue: (issue.code.value, issue.issue_id))
    )
    counts = Counter(issue.code.value for issue in sorted_issues)
    metrics: dict[str, int | float] = {
        "issue_count": len(sorted_issues),
        "warning_count": len(warnings),
        **{
            f"{code.value}_count": counts[code.value]
            for code in WikiSemanticIssueCode
        },
    }
    return WikiSemanticLintReport(
        issues=sorted_issues,
        warnings=tuple(dict.fromkeys(warnings)),
        metrics=metrics,
        model=model,
    )


def parse_wiki_semantic_lint_response(
    raw_response: str,
    *,
    context: WikiSemanticLintContext,
    model: str,
    issue_limit: int = 24,
) -> WikiSemanticLintReport:
    """LLM JSON 응답을 검증된 V3 의미 감사 보고서로 변환한다."""
    try:
        payload = json.loads(strip_json_fence(raw_response))
    except json.JSONDecodeError as error:
        raise ValueError(f"Wiki 의미 감사 응답이 JSON 형식이 아닙니다: {error}") from error
    if not isinstance(payload, Mapping):
        raise ValueError("Wiki 의미 감사 응답이 JSON 객체가 아닙니다.")
    raw_issues = payload.get("issues")
    if not isinstance(raw_issues, list):
        raise ValueError("Wiki 의미 감사 응답의 issues가 배열이 아닙니다.")
    if issue_limit < 0:
        raise ValueError("issue_limit은 0 이상이어야 합니다.")
    issues: list[WikiSemanticIssue] = []
    warnings: list[str] = []
    for index, raw in enumerate(raw_issues[:issue_limit], start=1):
        issue, warning = _parse_issue(raw, context=context)
        if issue is not None:
            issues.append(issue)
        elif warning is not None:
            warnings.append(f"issues[{index}]: {warning}")
    if len(raw_issues) > issue_limit:
        warnings.append(
            f"의미 감사 issue {len(raw_issues) - issue_limit}건을 상한에서 제외했습니다."
        )
    return _report(issues, warnings, model=model)


def _page_lines(context: WikiSemanticLintContext) -> list[str]:
    """현재 Page를 의미 감사 Prompt용 안정적인 한 줄 표현으로 만든다."""
    return [
        (
            f"- {page.reference}: {page.document_kind}:{page.document_key} / "
            f"title={page.title} / aliases={list(page.aliases)} / "
            f"summary={page.summary or '(없음)'} / sources={list(page.sources)}"
        )
        for page in context.pages
    ]


def _relation_lines(context: WikiSemanticLintContext) -> list[str]:
    """현재 관계를 Page 참조 endpoint로 변환해 Prompt에 넣는다."""
    references = {page.identity: page.reference for page in context.pages}
    lines: list[str] = []
    for relation in context.relations:
        source = references.get(
            WikiNodeIdentity(
                relation.source_document_kind,
                relation.source_document_key,
            )
        )
        target = references.get(
            WikiNodeIdentity(
                relation.target_document_kind,
                relation.target_document_key,
            )
        )
        if source and target:
            lines.append(f"- {source} -[{relation.relation_type}]-> {target}")
    return lines


def _source_blocks(context: WikiSemanticLintContext) -> list[str]:
    """활성 Source의 날짜·제목·제한 본문을 Prompt 블록으로 만든다."""
    return [
        (
            f"[{source.reference}] version={source.source_document_version_id} / "
            f"type={source.source_type} / published="
            f"{source.published_at.isoformat() if source.published_at else '-'} / "
            f"title={source.title}\n{source.content}"
        )
        for source in context.sources
    ]


def build_wiki_semantic_lint_prompt(context: WikiSemanticLintContext) -> str:
    """참조가 고정된 Page·Source·관계·후보를 LLM 사용자 Prompt로 직렬화한다."""
    candidate_lines = [
        (
            f"- {candidate.reference}: {candidate.source_page_reference} <-> "
            f"{candidate.target_page_reference} / score={candidate.score:.3f} / "
            f"signals={list(candidate.signals)}"
        )
        for candidate in context.relation_candidates
    ]
    sections = (
        "[현재 Page]\n" + "\n".join(_page_lines(context) or ["(없음)"]),
        "[현재 관계]\n" + "\n".join(_relation_lines(context) or ["(없음)"]),
        "[누락 관계 후보]\n"
        + "\n".join(candidate_lines or ["(없음)"]),
        "[활성 Source]\n\n" + "\n\n".join(_source_blocks(context) or ["(없음)"]),
    )
    return "\n\n".join(sections)


def audit_wiki_semantics(
    context: WikiSemanticLintContext,
    *,
    model: str = "gpt-4.1-mini",
    completion: WikiSemanticCompletion = complete,
    issue_limit: int = 24,
) -> WikiSemanticLintReport:
    """현재 Wiki와 활성 원본을 한 번 LLM 감사하고 검증 보고서를 반환한다."""
    if not context.pages and not context.sources:
        return _report([], [], model="deterministic:empty")
    raw_response = completion(
        _SYSTEM_PROMPT,
        build_wiki_semantic_lint_prompt(context),
        model=model,
    )
    return parse_wiki_semantic_lint_response(
        raw_response,
        context=context,
        model=model,
        issue_limit=issue_limit,
    )


__all__ = [
    "SEMANTIC_LINT_PROMPT_VERSION",
    "WikiMissingRelationProposal",
    "WikiMissingTopicProposal",
    "WikiSemanticEvidence",
    "WikiSemanticIssue",
    "WikiSemanticIssueCode",
    "WikiSemanticLintReport",
    "audit_wiki_semantics",
    "build_wiki_semantic_lint_prompt",
    "parse_wiki_semantic_lint_response",
]
