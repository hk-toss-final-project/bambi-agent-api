"""Global Source 수집·본문 저장 SQL의 동작을 검증한다.

네트워크·실제 DB 없이 순서별 Row를 반환하는 Connection Test Double로,
수집 워커의 중복 제거·저장과 Jina 워커의 본문 채우기 SQL 흐름을 확인한다.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from infrastructure.persistence.features.global_source import (
    GlobalArticleToFetch,
    claim_global_articles_for_fetch,
    mark_global_article_fetch_failed,
    persist_collected_articles,
    save_fetched_article_content,
)
from infrastructure.sources.connectors.api import LatestArticle


class _FakeCursor:
    """fetchone·fetchall을 지원하는 결정적 Cursor Test Double."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        """첫 번째 Row나 None을 반환한다."""
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        """전체 Row 목록을 반환한다."""
        return self._rows


class _FakeConnection:
    """SQL 호출 순서별 Row와 실행 내역을 보존하는 Connection Test Double."""

    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        self._responses = responses
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    async def execute(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> _FakeCursor:
        """SQL을 기록하고 순서별 고정 Cursor를 반환한다."""
        self.executed.append((query, params))
        rows = self._responses.pop(0) if self._responses else []
        return _FakeCursor(rows)


def _article(url: str, *, title: str = "제목") -> LatestArticle:
    """테스트용 정규화 기사 하나를 만든다."""
    return LatestArticle(
        provider="gdelt",
        title=title,
        url=url,
        description="설명",
        published_at=datetime(2026, 7, 20, tzinfo=UTC),
        source_name="example.com",
        language="ko",
    )


def test_persist_skips_existing_url_and_saves_new_as_pending() -> None:
    """이미 있는 URL은 건너뛰고 새 URL만 pending 문서로 저장하는지 검증한다."""
    connection = _FakeConnection(
        [
            [{"id": "source-1"}],  # INSERT global_sources
            [{"id": "run-1"}],  # INSERT global_collection_runs
            [],  # 기사1 존재 SELECT → 없음
            [{"id": "doc-1"}],  # INSERT wiki_documents
            [{"id": "ver-1"}],  # INSERT wiki_document_versions
            [],  # INSERT wiki_chunks
            [{"id": "existing"}],  # 기사2 존재 SELECT → 중복
            [],  # UPDATE global_collection_runs
        ]
    )

    result = asyncio.run(
        persist_collected_articles(
            connection,  # type: ignore[arg-type]
            provider="gdelt",
            query="AI Agent",
            articles=[
                _article("https://example.com/new"),
                _article("https://example.com/dup"),
            ],
        )
    )

    assert result["source_id"] == "source-1"
    assert result["run_id"] == "run-1"
    assert result["fetched_count"] == 2
    assert result["created_count"] == 1
    assert result["duplicate_count"] == 1
    items = result["items"]
    assert isinstance(items, list) and len(items) == 1
    assert items[0]["document_id"] == "doc-1"
    assert items[0]["content_status"] == "pending"
    document_sql, document_params = connection.executed[3]
    assert "INSERT INTO agent.wiki_documents" in document_sql
    assert document_params is not None
    assert document_params[4].obj["content_status"] == "pending"


def test_persist_counts_conflict_insert_as_duplicate() -> None:
    """동시 수집으로 INSERT가 충돌하면 중복으로 세는지 검증한다."""
    connection = _FakeConnection(
        [
            [{"id": "source-1"}],
            [{"id": "run-1"}],
            [],  # 존재 SELECT → 없음
            [],  # INSERT wiki_documents → ON CONFLICT DO NOTHING (Row 없음)
            [],  # UPDATE global_collection_runs
        ]
    )

    result = asyncio.run(
        persist_collected_articles(
            connection,  # type: ignore[arg-type]
            provider="naver",
            query="키워드",
            articles=[_article("https://example.com/race")],
        )
    )

    assert result["created_count"] == 0
    assert result["duplicate_count"] == 1
    assert result["items"] == []


def test_claim_returns_pending_articles() -> None:
    """pending 문서를 점유해 문서 ID·URL·Version으로 반환하는지 검증한다."""
    connection = _FakeConnection(
        [
            [
                {"id": "doc-1", "canonical_url": "https://a", "current_version": 1},
                {"id": "doc-2", "canonical_url": "https://b", "current_version": 1},
            ]
        ]
    )

    claimed = asyncio.run(
        claim_global_articles_for_fetch(connection, limit=5)  # type: ignore[arg-type]
    )

    assert claimed == [
        GlobalArticleToFetch(document_id="doc-1", url="https://a", current_version=1),
        GlobalArticleToFetch(document_id="doc-2", url="https://b", current_version=1),
    ]
    query, params = connection.executed[0]
    assert "content_status" in query
    assert "SKIP LOCKED" in query


def test_claim_rejects_out_of_range_limit() -> None:
    """Claim limit이 허용 범위를 벗어나면 ValueError를 발생시키는지 검증한다."""
    connection = _FakeConnection([])
    try:
        asyncio.run(
            claim_global_articles_for_fetch(connection, limit=0)  # type: ignore[arg-type]
        )
    except ValueError:
        pass
    else:  # pragma: no cover - 실패 경로
        raise AssertionError("범위를 벗어난 limit에서 ValueError가 필요합니다.")


def test_save_fetched_content_appends_new_version() -> None:
    """수집한 본문을 새 Version으로 추가하고 fetched로 전환하는지 검증한다."""
    connection = _FakeConnection(
        [
            [{"current_version": 1, "metadata": {"provider": "gdelt"}}],  # Head SELECT
            [{"id": "ver-2"}],  # INSERT version
            [],  # INSERT chunk
            [],  # UPDATE head
        ]
    )

    result = asyncio.run(
        save_fetched_article_content(
            connection,  # type: ignore[arg-type]
            document_id="doc-1",
            resolved_url="https://example.com/final",
            title="본문 제목",
            markdown="# 전체 본문\n\n내용",
            published_at=datetime(2026, 7, 20, tzinfo=UTC),
        )
    )

    assert result == {
        "document_id": "doc-1",
        "document_version_id": "ver-2",
        "version": 2,
        "content_status": "fetched",
    }
    version_sql, version_params = connection.executed[1]
    assert "INSERT INTO agent.wiki_document_versions" in version_sql
    assert version_params is not None
    assert version_params[1] == 2
    assert version_params[2] == "본문 제목"
    head_sql, head_params = connection.executed[3]
    assert "UPDATE agent.wiki_documents" in head_sql
    assert head_params is not None
    assert head_params[2].obj["content_status"] == "fetched"


def test_mark_failed_sets_failed_status() -> None:
    """본문 수집 실패 시 failed 상태와 오류 원인을 저장하는지 검증한다."""
    connection = _FakeConnection([[]])

    asyncio.run(
        mark_global_article_fetch_failed(
            connection,  # type: ignore[arg-type]
            document_id="doc-1",
            error_code="JINA_HTTP_404",
            error_message="not found",
        )
    )

    query, params = connection.executed[0]
    assert "UPDATE agent.wiki_documents" in query
    assert params is not None
    assert params[0].obj["content_status"] == "failed"
    assert params[0].obj["fetch_error_code"] == "JINA_HTTP_404"
