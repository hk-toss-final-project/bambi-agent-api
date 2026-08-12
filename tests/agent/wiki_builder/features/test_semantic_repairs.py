"""Personal Wiki V3 의미 감사 계획·원자 수리·Embedding 연결을 검증한다."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from agent.wiki_builder.features import semantic_repairs
from agent.wiki_builder.features.semantic_audit import (
    WikiMissingRelationProposal,
    WikiMissingTopicProposal,
    WikiSemanticEvidence,
    WikiSemanticIssue,
    WikiSemanticIssueCode,
    WikiSemanticLintReport,
)
from agent.wiki_builder.features.semantic_lint import (
    WikiGlobalRelationCandidate,
    WikiSemanticLintContext,
    WikiSemanticPage,
    WikiSemanticSource,
)
from agent.wiki_builder.features.semantic_repairs import (
    apply_wiki_semantic_repairs,
    plan_wiki_semantic_repairs,
    stage_wiki_semantic_repairs,
)
from infrastructure.persistence.api import (
    PersistedWikiBuild,
    PersistedWikiDocument,
    UserSourceDocumentForAgent,
)
from shared.wiki_models import ExistingWikiEntry


def _context(*, applied_issue_id: str | None = None) -> WikiSemanticLintContext:
    """두 Page·두 원본·누락 관계 후보가 있는 의미 감사 Context를 만든다."""
    seoul_metadata: dict[str, object] = {
        "aliases": ["서울시"],
        "sources": ["[[sources/weather|기상 기록]]"],
    }
    if applied_issue_id is not None:
        seoul_metadata["semantic_issue_ids"] = [applied_issue_id]
    return WikiSemanticLintContext(
        pages=(
            WikiSemanticPage(
                reference="P1",
                document_kind="entity",
                document_key="seoul",
                title="서울",
                summary="대한민국의 수도",
                aliases=("서울시",),
                sources=("[[sources/weather|기상 기록]]",),
                metadata=seoul_metadata,
            ),
            WikiSemanticPage(
                reference="P2",
                document_kind="concept",
                document_key="heatwave",
                title="폭염",
                summary="고온 현상",
                aliases=(),
                sources=("[[sources/weather|기상 기록]]",),
                metadata={"sources": ["[[sources/weather|기상 기록]]"]},
            ),
        ),
        sources=(
            WikiSemanticSource(
                reference="S1",
                source_document_version_id="source-v1",
                title="2026 기상 기록",
                content="서울의 최고 기온은 38도였다. 열대야가 10일 지속됐다.",
                source_type="web_clipping",
                canonical_url="https://example.com/weather-2026",
                published_at=None,
            ),
            WikiSemanticSource(
                reference="S2",
                source_document_version_id="source-v2",
                title="이전 기상 기록",
                content="서울의 최고 기온은 35도였다.",
                source_type="web_clipping",
                canonical_url="https://example.com/weather-2025",
                published_at=None,
            ),
        ),
        relations=(),
        relation_candidates=(
            WikiGlobalRelationCandidate(
                reference="C1",
                source_page_reference="P1",
                target_page_reference="P2",
                score=0.9,
                signals=("shared_source",),
            ),
        ),
    )


def _issue(
    issue_id: str,
    code: WikiSemanticIssueCode,
    *,
    pages: tuple[str, ...] = (),
    sources: tuple[str, ...] = ("S1",),
    evidence: tuple[WikiSemanticEvidence, ...] = (),
    topic: WikiMissingTopicProposal | None = None,
    relation: WikiMissingRelationProposal | None = None,
    query: str | None = None,
) -> WikiSemanticIssue:
    """테스트에 필요한 검증 완료 의미 문제를 만든다."""
    return WikiSemanticIssue(
        issue_id=issue_id,
        code=code,
        severity="warning",
        title=f"{code.value} 문제",
        rationale="검증된 원문 근거가 있습니다.",
        confidence=0.9,
        page_references=pages,
        source_references=sources,
        evidence=evidence,
        candidate_reference="C1" if relation is not None else None,
        topic=topic,
        relation=relation,
        research_query=query,
    )


def _report() -> WikiSemanticLintReport:
    """다섯 의미 감사 코드가 모두 포함된 보고서를 만든다."""
    evidence_2026 = WikiSemanticEvidence(
        "S1",
        "서울의 최고 기온은 38도였다.",
    )
    evidence_2025 = WikiSemanticEvidence(
        "S2",
        "서울의 최고 기온은 35도였다.",
    )
    issues = (
        _issue(
            "issue-contradiction",
            WikiSemanticIssueCode.CONTRADICTION,
            pages=("P1",),
            sources=("S1", "S2"),
            evidence=(evidence_2026, evidence_2025),
        ),
        _issue(
            "issue-stale",
            WikiSemanticIssueCode.STALE_CLAIM,
            pages=("P2",),
            sources=("S1", "S2"),
            evidence=(evidence_2026, evidence_2025),
        ),
        _issue(
            "issue-topic",
            WikiSemanticIssueCode.MISSING_TOPIC,
            pages=("P1",),
            evidence=(WikiSemanticEvidence("S1", "열대야가 10일 지속됐다."),),
            topic=WikiMissingTopicProposal(
                document_kind="concept",
                title="열대야",
                summary="밤에도 고온이 지속되는 현상",
                aliases=("Tropical night",),
                related_page_reference="P1",
                relation_type="associated_with",
                relation_direction="topic_to_page",
            ),
        ),
        _issue(
            "issue-relation",
            WikiSemanticIssueCode.MISSING_RELATION,
            pages=("P1", "P2"),
            evidence=(evidence_2026,),
            relation=WikiMissingRelationProposal(
                source_page_reference="P1",
                target_page_reference="P2",
                relation_type="applies_concept",
                evidence_source_reference="S1",
                evidence="서울의 최고 기온은 38도였다.",
                provenance_kind="source_explicit",
                confidence=0.9,
                rationale="서울 기상 기록이 폭염을 직접 설명합니다.",
            ),
        ),
        _issue(
            "issue-gap",
            WikiSemanticIssueCode.KNOWLEDGE_GAP,
            pages=("P2",),
            evidence=(),
            query="서울 폭염의 장기 추세",
        ),
    )
    return WikiSemanticLintReport(
        issues=issues,
        warnings=(),
        metrics={"issue_count": len(issues)},
        model="gpt-test",
    )


def _entries() -> list[ExistingWikiEntry]:
    """Context Page와 같은 현재 Wiki 값 객체를 만든다."""
    return [
        ExistingWikiEntry(
            document_kind=page.document_kind,
            document_key=page.document_key,
            title=page.title,
            domain="other",
            summary=page.summary,
            metadata=dict(page.metadata),
        )
        for page in _context().pages
    ]


def _source() -> UserSourceDocumentForAgent:
    """의미 수리 저장에 사용할 활성 원본 Version을 만든다."""
    return UserSourceDocumentForAgent(
        source_document_id="source-1",
        source_document_version_id="source-v1",
        source_event_id="event-1",
        user_id="user-1",
        namespace_key="user/user-1",
        source_type="web_clipping",
        canonical_url="https://example.com/weather-2026",
        version=1,
        title="2026 기상 기록",
        author=None,
        published_at=None,
        clipped_on=None,
        description=None,
        tags=["weather"],
        raw_content="서울의 최고 기온은 38도였다. 열대야가 10일 지속됐다.",
        content_hash="a" * 64,
    )


def test_plan_semantic_repairs_separates_internal_changes_and_research() -> None:
    """내부 문제와 외부 조사 항목을 분리한다."""
    plan = plan_wiki_semantic_repairs(_report(), context=_context())

    assert len(plan.batches) == 1
    assert plan.batches[0].source_document_version_id == "source-v1"
    assert set(plan.batches[0].issue_ids) == {
        "issue-contradiction",
        "issue-stale",
        "issue-topic",
        "issue-relation",
    }
    classification = plan.batches[0].classification
    assert {entity.name for entity in classification.entities} == {"서울"}
    assert {concept.title for concept in classification.concepts} == {"폭염", "열대야"}
    assert {relation.relation_type for relation in classification.relations} == {
        "associated_with",
        "applies_concept",
    }
    assert [issue.issue_id for issue in plan.research_issues] == ["issue-gap"]
    assert plan.metrics["planned_internal_issue_count"] == 4


def test_plan_semantic_repairs_skips_issue_already_recorded_on_page() -> None:
    """같은 의미 문제 ID가 Page Metadata에 있으면 재수리하지 않는다."""
    report = WikiSemanticLintReport(
        issues=(_report().issues[0],),
        warnings=(),
        metrics={},
        model="gpt-test",
    )

    plan = plan_wiki_semantic_repairs(
        report,
        context=_context(applied_issue_id="issue-contradiction"),
    )

    assert plan.batches == ()
    assert plan.skipped_issue_ids == ("issue-contradiction",)


def test_stage_semantic_repairs_preserves_claims_and_passes_quality_gate() -> None:
    """모순·오래된 주장을 보존하고 새 주제·관계와 함께 검증한다."""
    plan = plan_wiki_semantic_repairs(_report(), context=_context())

    staging = stage_wiki_semantic_repairs(
        plan,
        sources=[_source()],
        entries=_entries(),
        relations=[],
        model="gpt-test",
        generated_at="2026-08-12T00:00:00+00:00",
    )

    assert staging.quality.passed is True
    assert len(staging.batches) == 1
    planned = staging.batches[0].plan
    seoul = next(document for document in planned.entities if document.title == "서울")
    heatwave = next(document for document in planned.concepts if document.title == "폭염")
    tropical_night = next(
        document for document in planned.concepts if document.title == "열대야"
    )
    assert seoul.metadata["contradictions"][0]["id"] == "issue-contradiction"
    assert heatwave.metadata["stale_claims"][0]["id"] == "issue-stale"
    assert tropical_night.action == "create"
    assert {relation.relation_type for relation in planned.relations} == {
        "associated_with",
        "applies_concept",
    }


class _Connection:
    """의미 수리의 단일 Transaction 경계를 기록하는 연결 대역."""

    def __init__(self) -> None:
        """Transaction 진입 횟수를 0으로 초기화한다."""
        self.transactions = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """진입 횟수를 기록하는 빈 비동기 Transaction을 제공한다."""
        self.transactions += 1
        yield


def test_apply_semantic_repairs_uses_append_support_mode_and_embeds_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """단일 Transaction에서 기존 support를 보존하고 변경 Page만 임베딩한다."""
    connection = _Connection()
    persist_calls: list[dict[str, Any]] = []
    embed_calls: list[dict[str, Any]] = []

    async def fake_scope(*args: Any, **kwargs: Any) -> None:
        """테스트에서 실제 RLS SQL을 생략한다."""

    async def fake_persist(*args: Any, **kwargs: Any) -> PersistedWikiBuild:
        """저장 옵션을 기록하고 변경 문서 결과를 반환한다."""
        persist_calls.append(kwargs)
        return PersistedWikiBuild(
            wiki_version_id="wiki-v2",
            wiki_version=2,
            affected_documents=[
                PersistedWikiDocument(
                    document_id="document-seoul",
                    document_version_id="wiki-document-v2",
                    document_kind="entity",
                    document_key="seoul",
                    file_path="entities/seoul.md",
                    version=2,
                    action="update",
                ),
                PersistedWikiDocument(
                    document_id="document-schema",
                    document_version_id="schema-v2",
                    document_kind="schema",
                    document_key="schema",
                    file_path="schema.md",
                    version=2,
                    action="update",
                ),
            ],
            chunk_count=3,
            stored_relation_count=2,
        )

    async def fake_embed(*args: Any, **kwargs: Any) -> int:
        """Embedding 인자를 기록하고 한 건 저장 결과를 반환한다."""
        embed_calls.append(kwargs)
        return 1

    monkeypatch.setattr(semantic_repairs, "set_personal_wiki_scope", fake_scope)
    plan = plan_wiki_semantic_repairs(_report(), context=_context())

    result = asyncio.run(
        apply_wiki_semantic_repairs(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            repair_plan=plan,
            sources=[_source()],
            entries=_entries(),
            relations=[],
            model="gpt-test",
            embedding_model="embedding-test",
            persister=fake_persist,
            embedder=fake_embed,
            generated_at="2026-08-12T00:00:00+00:00",
        )
    )

    assert connection.transactions == 1
    assert persist_calls[0]["replace_source_relation_supports"] is False
    assert embed_calls[0]["document_version_ids"] == ("wiki-document-v2",)
    assert embed_calls[0]["model"] == "embedding-test"
    assert result.wiki_version_id == "wiki-v2"
    assert result.embedding_count == 1
    assert set(result.repaired_issue_ids) == {
        "issue-contradiction",
        "issue-stale",
        "issue-topic",
        "issue-relation",
    }
