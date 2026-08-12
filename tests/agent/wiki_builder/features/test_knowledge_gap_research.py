"""Wiki V3 지식 공백의 기존 URL 수집·쓰기 루프 연결을 검증한다."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from agent.wiki_builder.features import knowledge_gap_research
from agent.wiki_builder.features.knowledge_gap_research import (
    WikiKnowledgeGapResearchLimits,
    research_wiki_knowledge_gaps,
)
from agent.wiki_builder.features.semantic_audit import (
    WikiSemanticIssue,
    WikiSemanticIssueCode,
)
from shared.report_models import ReportContextDocument


class _Connection:
    """URL별 독립 Transaction 진입 횟수를 기록하는 연결 대역."""

    def __init__(self) -> None:
        """Transaction 횟수를 0으로 초기화한다."""
        self.transactions = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """진입 횟수만 기록하는 빈 비동기 Transaction을 제공한다."""
        self.transactions += 1
        yield


def _gap(issue_id: str, query: str) -> WikiSemanticIssue:
    """외부 조사 질의가 검증된 지식 공백 문제를 만든다."""
    return WikiSemanticIssue(
        issue_id=issue_id,
        code=WikiSemanticIssueCode.KNOWLEDGE_GAP,
        severity="warning",
        title="외부 지식 공백",
        rationale="현재 원본만으로 최신 사실을 채울 수 없습니다.",
        confidence=0.9,
        page_references=("P1",),
        source_references=(),
        evidence=(),
        research_query=query,
    )


def _document(index: int, url: str | None) -> ReportContextDocument:
    """Live 수집기가 반환할 URL 중심 Context 문서를 만든다."""
    return ReportContextDocument(
        reference=f"L{index}",
        document_version_id="",
        chunk_id=f"L{index}",
        namespace_key="global/live",
        title=f"자료 {index}",
        content="외부 자료 요약",
        url=url,
        score=1.0,
    )


def test_research_limits_queries_filters_urls_and_enqueues_write_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """질의·URL 상한과 공개 주소 필터를 적용해 수집 Job만 등록한다."""
    connection = _Connection()
    queries: list[str] = []
    registrations: list[dict[str, Any]] = []

    async def fake_scope(*args: Any, **kwargs: Any) -> None:
        """테스트에서 실제 RLS SQL을 생략한다."""

    def collector(topic: str, user_id: str, **kwargs: Any) -> list[ReportContextDocument]:
        """첫 질의에는 중복·사설 URL, 둘째 질의에는 공개 URL을 반환한다."""
        queries.append(topic)
        if topic == "query-a":
            return [
                _document(1, "https://Example.com/a#section"),
                _document(2, "https://example.com/a"),
                _document(3, "http://127.0.0.1/admin"),
                _document(4, "https://example.org/b"),
            ]
        return [
            _document(5, "https://example.net/c"),
            _document(6, "https://example.edu/d"),
        ]

    async def registrar(*args: Any, **kwargs: Any) -> None:
        """기존 URL 수집 Job 등록 인자를 기록한다."""
        registrations.append(kwargs)

    monkeypatch.setattr(
        knowledge_gap_research,
        "set_personal_wiki_scope",
        fake_scope,
    )

    result = asyncio.run(
        research_wiki_knowledge_gaps(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            job_id="maintenance-job-1",
            issues=[_gap("issue-b", "query-b"), _gap("issue-a", "query-a")],
            model="model-test",
            limits=WikiKnowledgeGapResearchLimits(
                query_limit=2,
                documents_per_query=5,
                url_limit=3,
            ),
            collector=collector,
            registrar=registrar,  # type: ignore[arg-type]
        )
    )

    assert queries == ["query-a", "query-b"]
    assert [call["url"] for call in registrations] == [
        "https://example.com/a",
        "https://example.org/b",
        "https://example.net/c",
    ]
    assert all(
        call["request_id"] == "wiki-maintenance:maintenance-job-1"
        for call in registrations
    )
    assert all(
        call["source_event_id"].startswith("wiki-v3:issue-")
        for call in registrations
    )
    assert connection.transactions == 3
    assert result.query_count == 2
    assert result.collected_document_count == 6
    assert result.queued_source_count == 3


def test_research_continues_after_one_url_registration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """한 URL 등록 실패를 경고로 남기고 다음 공개 URL은 계속 등록한다."""
    connection = _Connection()
    attempts = 0

    async def fake_scope(*args: Any, **kwargs: Any) -> None:
        """테스트에서 실제 RLS SQL을 생략한다."""

    def collector(*args: Any, **kwargs: Any) -> list[ReportContextDocument]:
        """서로 다른 공개 URL 두 건을 반환한다."""
        return [
            _document(1, "https://example.com/first"),
            _document(2, "https://example.com/second"),
        ]

    async def registrar(*args: Any, **kwargs: Any) -> None:
        """첫 등록만 실패시키고 두 번째는 성공시킨다."""
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("등록 실패")

    monkeypatch.setattr(
        knowledge_gap_research,
        "set_personal_wiki_scope",
        fake_scope,
    )

    result = asyncio.run(
        research_wiki_knowledge_gaps(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            issues=[_gap("issue-a", "query-a")],
            model="model-test",
            collector=collector,
            registrar=registrar,  # type: ignore[arg-type]
        )
    )

    assert attempts == 2
    assert connection.transactions == 2
    assert result.queued_source_count == 1
    assert result.warnings == ("issue-a: URL 등록 실패(RuntimeError)",)


def test_research_with_no_knowledge_gap_does_not_call_external_boundaries() -> None:
    """지식 공백이 없으면 Live 수집·DB Transaction을 모두 건너뛴다."""
    connection = _Connection()

    def unexpected(*args: Any, **kwargs: Any) -> list[ReportContextDocument]:
        """호출되면 실패해 불필요한 외부 수집을 감지한다."""
        raise AssertionError("지식 공백 없이 외부 수집하면 안 됩니다.")

    result = asyncio.run(
        research_wiki_knowledge_gaps(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            issues=[],
            model="model-test",
            collector=unexpected,
        )
    )

    assert result.query_count == 0
    assert result.queued_source_count == 0
    assert connection.transactions == 0


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "http://localhost/admin",
        "http://10.0.0.1/private",
        "https://user:secret@example.com/path",
        "https://example.com:bad/path",
    ],
)
def test_research_rejects_non_public_or_malformed_urls(url: str) -> None:
    """비공개·인증 포함·잘못된 URL을 Source로 등록하지 않는다."""
    connection = _Connection()

    def collector(*args: Any, **kwargs: Any) -> list[ReportContextDocument]:
        """검증 대상 URL 한 건을 반환한다."""
        return [_document(1, url)]

    result = asyncio.run(
        research_wiki_knowledge_gaps(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            issues=[_gap("issue-a", "query-a")],
            model="model-test",
            collector=collector,
        )
    )

    assert result.queued_source_count == 0
    assert connection.transactions == 0
