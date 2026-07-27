"""사용자 클리핑·URL 원본과 Job의 원자적 저장 SQL을 검증한다."""

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from infrastructure.persistence.features.source_ingestion import (
    PersistedSourceSubmission,
    save_web_clipping_and_enqueue,
)


class _FakeCursor:
    """한 SQL 호출에 지정된 Row를 반환하는 Cursor Test Double."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        """지정된 단일 Row를 반환한다."""
        return self._row


class _SequencedConnection:
    """SQL 호출 순서별 Row와 실행 내역을 보존하는 Connection Test Double."""

    def __init__(self, rows: list[dict[str, Any] | None]) -> None:
        self._rows = list(rows)
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, params: tuple[Any, ...]) -> _FakeCursor:
        """SQL과 Parameter를 기록하고 다음 Row를 반환한다."""
        self.executed.append((query, params))
        return _FakeCursor(self._rows.pop(0) if self._rows else None)


def test_save_web_clipping_persists_frontmatter_and_wiki_job() -> None:
    """클리핑 Frontmatter·Markdown과 Wiki Job이 같은 실행 경계에 포함되는지 검증한다."""
    connection = _SequencedConnection(
        [
            {"id": "event-1"},
            None,
            {"id": "source-1"},
            None,
            {"id": "source-version-1"},
            None,
            {"id": "job-1"},
            None,
        ]
    )

    result = asyncio.run(
        save_web_clipping_and_enqueue(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_event_id="clip-1",
            source_url="https://example.com/article",
            title="제목",
            content="# Markdown 본문",
            author="작성자",
            published_at=datetime(2026, 7, 1, tzinfo=UTC),
            clipped_on=date(2026, 7, 16),
            description="설명",
            tags=["ai", "wiki"],
            occurred_at=None,
            memo="중요",
            request_id="request-1",
        )
    )

    assert result == PersistedSourceSubmission(
        source_document_id="source-1",
        source_document_version_id="source-version-1",
        source_version=1,
        source_event_row_id="event-1",
        job_id="job-1",
        job_created=True,
    )
    version_sql, version_params = connection.executed[4]
    assert "agent.user_source_document_versions" in version_sql
    assert version_params[4:11] == (
        "제목",
        "작성자",
        datetime(2026, 7, 1, tzinfo=UTC),
        date(2026, 7, 16),
        "설명",
        ["ai", "wiki"],
        "# Markdown 본문",
    )
    job_sql, job_params = connection.executed[6]
    assert "'personal_wiki_build'" in job_sql
    assert job_params is not None
    assert job_params[0] == "SVC-002"
    assert job_params[2] == "clip-1:v1"
    assert job_params[4] == "request-1"


def test_save_web_clipping_reuses_same_source_version_and_job() -> None:
    """같은 본문 재요청이 원본 Version과 Wiki Job을 중복 생성하지 않는지 검증한다."""
    from agent.wiki_builder.features.vault import compute_content_hash

    content = "# 동일 본문"
    connection = _SequencedConnection(
        [
            {"id": "event-1"},
            {"id": "source-1"},
            {
                "id": "source-version-1",
                "version": 1,
                "content_hash": compute_content_hash(content),
            },
            None,
            {"id": "job-1"},
            None,
        ]
    )

    result = asyncio.run(
        save_web_clipping_and_enqueue(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_event_id="clip-1",
            source_url="https://example.com/article",
            title="제목",
            content=content,
            author=None,
            published_at=None,
            clipped_on=None,
            description=None,
            tags=[],
            occurred_at=None,
            memo=None,
            request_id="request-2",
        )
    )

    assert result.source_document_version_id == "source-version-1"
    assert result.job_id == "job-1"
    assert not any(
        "INSERT INTO agent.user_source_document_versions" in sql
        for sql, _ in connection.executed
    )


def test_save_content_mark_materializes_candidate_and_enqueues_job() -> None:
    """위키마킹이 생성 후보 본문을 원본 Version으로 복사하고 Job을 등록하는지 검증한다."""
    from infrastructure.persistence.features.source_ingestion import (
        save_content_mark_and_enqueue,
    )

    connection = _SequencedConnection(
        [
            {
                "content_id": "content-1",
                "version": 2,
                "content_type": "interest_news_card",
                "title": "생성 리포트 제목",
                "summary": "생성 요약",
                "body": "# 생성 본문",
            },
            {"id": "event-1"},
            None,
            {"id": "source-1"},
            None,
            {"id": "source-version-1"},
            None,
            {"id": "job-1"},
            None,
        ]
    )

    result = asyncio.run(
        save_content_mark_and_enqueue(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_event_id="mark-1",
            content_id="content-1",
            occurred_at=None,
            memo="저장",
            request_id="request-1",
        )
    )

    assert result.source_document_id == "source-1"
    assert result.source_document_version_id == "source-version-1"
    assert result.job_id == "job-1"
    candidate_sql, candidate_params = connection.executed[0]
    assert "agent.generated_content_candidates" in candidate_sql
    assert candidate_params[0] == "user-1"
    event_sql, event_params = connection.executed[1]
    assert "'content_mark'" in event_sql
    assert event_params[3] == "content-1"
    head_sql, head_params = connection.executed[3]
    assert "agent.user_source_documents" in head_sql
    assert "content_mark" in head_params
    version_sql, version_params = connection.executed[5]
    assert "agent.user_source_document_versions" in version_sql
    assert version_params[4] == "생성 리포트 제목"
    assert version_params[10] == "# 생성 본문"
    job_sql, job_params = connection.executed[7]
    assert "'personal_wiki_build'" in job_sql
    assert job_params[0] == "SVC-004"


def test_save_content_mark_rejects_unknown_candidate() -> None:
    """대상 생성 콘텐츠가 없으면 저장 없이 도메인 오류를 던지는지 검증한다."""
    import pytest

    from infrastructure.persistence.features.source_ingestion import (
        GeneratedContentNotFoundError,
        save_content_mark_and_enqueue,
    )

    connection = _SequencedConnection([None])

    with pytest.raises(GeneratedContentNotFoundError):
        asyncio.run(
            save_content_mark_and_enqueue(
                connection,  # type: ignore[arg-type]
                user_id="user-1",
                source_event_id="mark-unknown",
                content_id="missing",
                occurred_at=None,
                memo=None,
                request_id="request-1",
            )
        )

    assert len(connection.executed) == 1
