"""Personal Wiki V3 LLM 의미 감사의 결정적 검증을 테스트한다."""

import json

import pytest

from agent.wiki_builder.features.semantic_audit import (
    WikiSemanticIssueCode,
    WikiSemanticLintReport,
    audit_wiki_semantics,
    build_wiki_semantic_lint_prompt,
    parse_wiki_semantic_lint_response,
)
from agent.wiki_builder.features.semantic_lint import (
    WikiSemanticLintContext,
    WikiSemanticSourceDocument,
    build_wiki_semantic_lint_context,
)
from shared.wiki_models import ExistingWikiEntry


def _entry(
    kind: str,
    key: str,
    title: str,
    summary: str,
    *,
    aliases: list[str] | None = None,
    sources: list[str] | None = None,
    related_concepts: list[str] | None = None,
) -> ExistingWikiEntry:
    """의미 감사 테스트용 현재 Wiki Page를 만든다."""
    return ExistingWikiEntry(
        document_kind=kind,
        document_key=key,
        title=title,
        domain="other",
        summary=summary,
        metadata={
            "aliases": aliases or [],
            "sources": sources or [],
            "related_concepts": related_concepts or [],
        },
    )


def _context_entries() -> list[ExistingWikiEntry]:
    """공통 의미 감사 테스트에 사용할 두 Wiki Page를 만든다."""
    return [
        _entry(
            "concept",
            "agent",
            "AI 에이전트",
            "도구를 사용해 작업을 수행하는 시스템",
            sources=["[[sources/one|첫 글]]"],
            related_concepts=["검색 증강 생성"],
        ),
        _entry(
            "concept",
            "rag",
            "RAG",
            "외부 지식을 검색해 생성을 보강하는 방법",
            aliases=["검색 증강 생성"],
            sources=["[[sources/two|둘째 글]]"],
        ),
    ]


def _context_sources() -> list[WikiSemanticSourceDocument]:
    """공통 의미 감사 테스트에 사용할 두 활성 Source를 만든다."""
    return [
        WikiSemanticSourceDocument(
            source_document_version_id="source-v1",
            title="기존 설명",
            raw_content=(
                "2025년 제품은 단일 에이전트만 지원한다. "
                "Agentic RAG는 AI 에이전트가 RAG를 사용해 지식을 찾는 방식이다."
            ),
        ),
        WikiSemanticSourceDocument(
            source_document_version_id="source-v2",
            title="새 설명",
            raw_content=(
                "2026년 업데이트부터 제품은 멀티 에이전트를 지원한다. "
                "평가 루프는 여러 문서에서 반복되는 핵심 방법이다."
            ),
        ),
    ]


def _context() -> WikiSemanticLintContext:
    """두 Page·두 Source·누락 관계 후보가 있는 공통 테스트 입력을 만든다."""
    return build_wiki_semantic_lint_context(
        _context_entries(),
        [],
        _context_sources(),
    )


def _issue(**overrides: object) -> dict[str, object]:
    """유효한 missing_relation JSON에 필요한 필드를 기본으로 채운다."""
    value: dict[str, object] = {
        "code": "missing_relation",
        "severity": "warning",
        "title": "Agentic RAG 연결 누락",
        "rationale": "원문이 AI 에이전트와 RAG의 사용 관계를 직접 설명한다.",
        "confidence": 0.92,
        "page_refs": ["P1", "P2"],
        "source_refs": ["S1"],
        "evidence": [
            {
                "source_ref": "S1",
                "quote": "Agentic RAG는 AI 에이전트가 RAG를 사용해 지식을 찾는 방식이다.",
            }
        ],
        "candidate_ref": "C1",
        "topic": None,
        "relation": {
            "source_page_ref": "P1",
            "target_page_ref": "P2",
            "relation_type": "associated_with",
            "evidence_source_ref": "S1",
            "evidence": "Agentic RAG는 AI 에이전트가 RAG를 사용해 지식을 찾는 방식이다.",
            "provenance_kind": "source_explicit",
            "confidence": 0.92,
            "rationale": "에이전트가 RAG를 지식 검색 방식으로 사용한다.",
        },
        "research_query": None,
    }
    value.update(overrides)
    return value


def _parse(issue: dict[str, object]) -> WikiSemanticLintReport:
    """문제 한 건을 공통 Context에서 의미 감사 보고서로 파싱한다."""
    return parse_wiki_semantic_lint_response(
        json.dumps({"issues": [issue]}, ensure_ascii=False),
        context=_context(),
        model="test-model",
    )


def test_valid_missing_relation_is_accepted_with_stable_issue_id() -> None:
    """후보 endpoint와 원문 인용이 맞는 누락 관계만 구조화한다."""
    first = _parse(_issue())
    second = _parse(_issue())

    assert first.warnings == ()
    assert first.issues[0].code is WikiSemanticIssueCode.MISSING_RELATION
    assert first.issues[0].relation is not None
    assert first.issues[0].issue_id == second.issues[0].issue_id
    assert first.metrics["missing_relation_count"] == 1


def test_issue_id_survives_page_and_source_reference_reordering() -> None:
    """앞쪽 Page·Source가 추가돼 P·S 순번이 바뀌어도 같은 문제 ID를 유지한다."""
    original_issue = _issue(
        code="stale_claim",
        title="단일 에이전트 지원 설명이 오래됨",
        rationale="2026년 업데이트가 과거 제한을 명시적으로 바꿨다.",
        confidence=0.94,
        page_refs=["P1"],
        source_refs=["S1", "S2"],
        evidence=[
            {
                "source_ref": "S1",
                "quote": "2025년 제품은 단일 에이전트만 지원한다.",
            },
            {
                "source_ref": "S2",
                "quote": "2026년 업데이트부터 제품은 멀티 에이전트를 지원한다.",
            },
        ],
        candidate_ref=None,
        relation=None,
    )
    original = _parse(original_issue)
    reordered_context = build_wiki_semantic_lint_context(
        [
            _entry("concept", "aaa", "선행 Page", "참조 순번 변경용 Page"),
            *_context_entries(),
        ],
        [],
        [
            WikiSemanticSourceDocument(
                source_document_version_id="source-v0",
                title="선행 Source",
                raw_content="참조 순번 변경용 원본이다.",
            ),
            *_context_sources(),
        ],
    )
    reordered_issue = dict(original_issue)
    reordered_issue.update(
        {
            "page_refs": ["P2"],
            "source_refs": ["S2", "S3"],
            "evidence": [
                {
                    "source_ref": "S2",
                    "quote": "2025년 제품은 단일 에이전트만 지원한다.",
                },
                {
                    "source_ref": "S3",
                    "quote": "2026년 업데이트부터 제품은 멀티 에이전트를 지원한다.",
                },
            ],
        }
    )
    reordered = parse_wiki_semantic_lint_response(
        json.dumps({"issues": [reordered_issue]}, ensure_ascii=False),
        context=reordered_context,
        model="test-model",
    )

    assert original.issues[0].issue_id == reordered.issues[0].issue_id


def test_distinct_claim_evidence_gets_distinct_issue_ids() -> None:
    """같은 Page·Source 범위라도 서로 다른 주장 근거는 별도 문제로 식별한다."""
    first = _parse(
        _issue(
            code="stale_claim",
            confidence=0.94,
            page_refs=["P1"],
            source_refs=["S1", "S2"],
            evidence=[
                {
                    "source_ref": "S1",
                    "quote": "2025년 제품은 단일 에이전트만 지원한다.",
                },
                {
                    "source_ref": "S2",
                    "quote": "2026년 업데이트부터 제품은 멀티 에이전트를 지원한다.",
                },
            ],
            candidate_ref=None,
            relation=None,
        )
    )
    second = _parse(
        _issue(
            code="stale_claim",
            confidence=0.94,
            page_refs=["P1"],
            source_refs=["S1", "S2"],
            evidence=[
                {
                    "source_ref": "S1",
                    "quote": "단일 에이전트만 지원한다.",
                },
                {
                    "source_ref": "S2",
                    "quote": "멀티 에이전트를 지원한다.",
                },
            ],
            candidate_ref=None,
            relation=None,
        )
    )

    assert first.issues[0].issue_id != second.issues[0].issue_id


def test_missing_relation_outside_candidate_scope_is_rejected() -> None:
    """LLM이 후보에 없는 Page 참조를 관계 endpoint로 바꾸면 제외한다."""
    relation = dict(_issue()["relation"])
    relation["target_page_ref"] = "P9"

    report = _parse(_issue(relation=relation))

    assert report.issues == ()
    assert "후보 endpoint" in report.warnings[0]


def test_hallucinated_evidence_is_rejected() -> None:
    """Source 본문에 없는 인용을 사용한 문제는 후속 수정으로 전달하지 않는다."""
    report = _parse(
        _issue(evidence=[{"source_ref": "S1", "quote": "존재하지 않는 문장"}])
    )

    assert report.issues == ()
    assert "원문과 다릅니다" in report.warnings[0]


def test_contradiction_requires_two_distinct_source_evidences() -> None:
    """한 Source의 문장 하나만으로 모순을 확정하지 않는다."""
    report = _parse(
        _issue(
            code="contradiction",
            candidate_ref=None,
            relation=None,
            confidence=0.9,
        )
    )

    assert report.issues == ()
    assert "서로 다른 Source" in report.warnings[0]


def test_stale_claim_accepts_explicit_old_and_new_source_evidence() -> None:
    """새 Source가 변화를 명시하고 양쪽 인용이 있을 때 오래된 주장을 기록한다."""
    report = _parse(
        _issue(
            code="stale_claim",
            title="단일 에이전트 지원 설명이 오래됨",
            rationale="2026년 업데이트가 과거 제한을 명시적으로 바꿨다.",
            confidence=0.94,
            page_refs=["P1"],
            source_refs=["S1", "S2"],
            evidence=[
                {
                    "source_ref": "S1",
                    "quote": "2025년 제품은 단일 에이전트만 지원한다.",
                },
                {
                    "source_ref": "S2",
                    "quote": "2026년 업데이트부터 제품은 멀티 에이전트를 지원한다.",
                },
            ],
            candidate_ref=None,
            relation=None,
        )
    )

    assert report.warnings == ()
    assert report.issues[0].code is WikiSemanticIssueCode.STALE_CLAIM


def test_missing_topic_rejects_existing_title_or_alias() -> None:
    """기존 Page alias와 같은 제안은 누락 주제로 새로 만들지 않는다."""
    report = _parse(
        _issue(
            code="missing_topic",
            rationale="원본에서 반복된다.",
            confidence=0.9,
            page_refs=["P1"],
            source_refs=["S1"],
            candidate_ref=None,
            relation=None,
            topic={
                "document_kind": "concept",
                "title": "검색 증강 생성",
                "summary": "외부 자료를 검색한다.",
                "aliases": [],
                "related_page_ref": "P1",
                "relation_type": "associated_with",
                "relation_direction": "topic_to_page",
            },
        )
    )

    assert report.issues == ()
    assert "새 Page" in report.warnings[0]


def test_valid_missing_topic_keeps_source_grounded_proposal() -> None:
    """새 표면형·설명·근거를 가진 누락 주제는 Page 복구 입력으로 보존한다."""
    report = _parse(
        _issue(
            code="missing_topic",
            title="평가 루프 Page 누락",
            rationale="새 원본에서 핵심 방법으로 명시한다.",
            confidence=0.9,
            page_refs=["P1"],
            source_refs=["S2"],
            evidence=[
                {
                    "source_ref": "S2",
                    "quote": "평가 루프는 여러 문서에서 반복되는 핵심 방법이다.",
                }
            ],
            candidate_ref=None,
            relation=None,
            topic={
                "document_kind": "concept",
                "title": "평가 루프",
                "summary": "결과를 평가하고 다음 실행을 조정하는 반복 방법",
                "aliases": ["Evaluation loop"],
                "related_page_ref": "P1",
                "relation_type": "associated_with",
                "relation_direction": "topic_to_page",
            },
        )
    )

    assert report.issues[0].topic is not None
    assert report.issues[0].topic.title == "평가 루프"


def test_knowledge_gap_normalizes_and_limits_research_query() -> None:
    """외부 수집 질의는 공백을 정리하고 저장 가능한 길이로 제한한다."""
    query = "  2026년   Agentic RAG 표준 현황 " + "상세" * 100
    report = _parse(
        _issue(
            code="knowledge_gap",
            rationale="활성 원본에는 최신 표준 비교가 없다.",
            confidence=0.9,
            page_refs=["P1", "P2"],
            source_refs=[],
            evidence=[],
            candidate_ref=None,
            relation=None,
            research_query=query,
        )
    )

    assert report.issues[0].research_query is not None
    assert report.issues[0].research_query.startswith("2026년 Agentic RAG")
    assert len(report.issues[0].research_query) == 200


def test_low_confidence_and_unknown_issue_are_reported_not_applied() -> None:
    """임계값 미달과 지원하지 않는 코드는 경고로 남기고 수정에서 제외한다."""
    response = {
        "issues": [
            _issue(confidence=0.2),
            _issue(code="delete_everything"),
        ]
    }

    report = parse_wiki_semantic_lint_response(
        json.dumps(response, ensure_ascii=False),
        context=_context(),
        model="test-model",
    )

    assert report.issues == ()
    assert len(report.warnings) == 2


def test_invalid_json_or_issue_array_raises_for_job_retry() -> None:
    """응답 전체가 깨졌으면 건강한 Wiki로 오판하지 않고 실행 실패로 처리한다."""
    with pytest.raises(ValueError, match="JSON 형식"):
        parse_wiki_semantic_lint_response(
            "not-json",
            context=_context(),
            model="test-model",
        )
    with pytest.raises(ValueError, match="issues가 배열"):
        parse_wiki_semantic_lint_response(
            '{}',
            context=_context(),
            model="test-model",
        )


def test_prompt_contains_stable_references_and_treats_source_as_data() -> None:
    """Prompt는 Page·Source·후보 참조와 원문을 명시된 데이터 섹션에 넣는다."""
    prompt = build_wiki_semantic_lint_prompt(_context())

    assert "[현재 Page]" in prompt
    assert "P1: concept:agent" in prompt
    assert "[누락 관계 후보]" in prompt
    assert "C1: P1 <-> P2" in prompt
    assert "[S1] version=source-v1" in prompt


def test_audit_calls_llm_once_and_parses_result() -> None:
    """의미 감사는 고정 Prompt로 LLM을 한 번 호출하고 검증 결과를 반환한다."""
    calls: list[tuple[str, str, str]] = []

    def completion(system: str, user: str, *, model: str) -> str:
        """호출 내용을 기록하고 문제가 없는 응답을 반환한다."""
        calls.append((system, user, model))
        return '{"issues": []}'

    report = audit_wiki_semantics(
        _context(),
        model="test-model",
        completion=completion,
    )

    assert len(calls) == 1
    assert calls[0][2] == "test-model"
    assert report.issues == ()
    assert report.model == "test-model"


def test_empty_context_skips_llm_call() -> None:
    """Page와 Source가 모두 없으면 비용 없이 빈 보고서를 반환한다."""
    context = build_wiki_semantic_lint_context([], [], [])

    def unexpected(*_args: object, **_kwargs: object) -> str:
        """호출되면 테스트를 실패시킨다."""
        raise AssertionError("빈 의미 감사에서 LLM을 호출하면 안 됩니다.")

    report = audit_wiki_semantics(context, completion=unexpected)

    assert report.issues == ()
    assert report.model == "deterministic:empty"
