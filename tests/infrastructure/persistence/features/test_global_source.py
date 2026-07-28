"""Global Source 수집·본문 저장 SQL의 동작을 검증한다.

네트워크·실제 DB 없이 순서별 Row를 반환하는 Connection Test Double로,
수집 워커의 중복 제거·저장과 Jina 워커의 본문 채우기 SQL 흐름을 확인한다.
저장 대상은 소유권 없는 수집 캐시(`agent.global_source_documents`)다.
"""

import asyncio
import json
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
    """이미 있는 URL은 건너뛰고 새 URL만 pending 캐시 문서로 저장하는지 검증한다."""
    connection = _FakeConnection(
        [
            [{"id": "source-1"}],  # INSERT global_sources
            [{"id": "run-1"}],  # INSERT global_collection_runs
            [{"id": "doc-1"}],  # 기사1 INSERT → 새 캐시 문서
            [],  # 기사2 INSERT → ON CONFLICT DO NOTHING (중복)
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
    document_sql, document_params = connection.executed[2]
    assert "INSERT INTO agent.global_source_documents" in document_sql
    assert "ON CONFLICT (canonical_url) DO NOTHING" in document_sql
    assert document_params is not None
    assert document_params[8] == "pending"


def test_persist_returns_json_serializable_published_at() -> None:
    """저장 결과의 published_at이 JSON으로 바로 직렬화되는 문자열인지 검증한다.

    published_at을 datetime 그대로 반환하면 워커가 결과를 json.dumps할 때
    TypeError가 발생하므로, isoformat 문자열로 변환됐는지와 결과 전체가
    default 인자 없이 직렬화되는지 확인한다.
    """
    connection = _FakeConnection(
        [
            [{"id": "source-1"}],  # INSERT global_sources
            [{"id": "run-1"}],  # INSERT global_collection_runs
            [{"id": "doc-1"}],  # 기사 INSERT → 새 캐시 문서
            [],  # UPDATE global_collection_runs
        ]
    )

    result = asyncio.run(
        persist_collected_articles(
            connection,  # type: ignore[arg-type]
            provider="gdelt",
            query="AI Agent",
            articles=[_article("https://example.com/new")],
        )
    )

    items = result["items"]
    assert isinstance(items, list) and len(items) == 1
    assert items[0]["published_at"] == "2026-07-20T00:00:00+00:00"
    # default 없이도 직렬화되어야 한다(워커가 실제로 이렇게 출력한다).
    json.dumps(result, ensure_ascii=False)


def test_persist_counts_conflict_insert_as_duplicate() -> None:
    """이미 캐시에 있는 URL의 INSERT 충돌을 중복으로 세는지 검증한다."""
    connection = _FakeConnection(
        [
            [{"id": "source-1"}],
            [{"id": "run-1"}],
            [],  # INSERT → ON CONFLICT DO NOTHING (Row 없음)
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
    """pending 캐시 문서를 점유해 문서 ID·URL로 반환하는지 검증한다."""
    connection = _FakeConnection(
        [
            [
                {"id": "doc-1", "canonical_url": "https://a"},
                {"id": "doc-2", "canonical_url": "https://b"},
            ]
        ]
    )

    claimed = asyncio.run(
        claim_global_articles_for_fetch(connection, limit=5)  # type: ignore[arg-type]
    )

    assert claimed == [
        GlobalArticleToFetch(document_id="doc-1", url="https://a"),
        GlobalArticleToFetch(document_id="doc-2", url="https://b"),
    ]
    query, params = connection.executed[0]
    assert "agent.global_source_documents" in query
    assert "content_status = 'pending'" in query
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


def test_save_fetched_content_fills_cache_document() -> None:
    """수집한 본문을 캐시 문서에 채우고 fetched로 전환하는지 검증한다."""
    connection = _FakeConnection([[{"id": "doc-1"}]])

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
        "content_status": "fetched",
    }
    update_sql, update_params = connection.executed[0]
    assert "UPDATE agent.global_source_documents" in update_sql
    assert "content_status = 'fetched'" in update_sql
    assert update_params is not None
    assert update_params[0] == "본문 제목"
    assert update_params[1] == "# 전체 본문\n\n내용"
    assert update_params[3] == "https://example.com/final"


def test_save_fetched_content_raises_for_missing_document() -> None:
    """존재하지 않는 캐시 문서에 본문을 저장하려 하면 RuntimeError를 낸다."""
    connection = _FakeConnection([[]])

    try:
        asyncio.run(
            save_fetched_article_content(
                connection,  # type: ignore[arg-type]
                document_id="missing",
                resolved_url="https://example.com/final",
                title="본문 제목",
                markdown="본문",
                published_at=None,
            )
        )
    except RuntimeError:
        pass
    else:  # pragma: no cover - 실패 경로
        raise AssertionError("없는 문서 저장에서 RuntimeError가 필요합니다.")


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
    assert "UPDATE agent.global_source_documents" in query
    assert "content_status = 'failed'" in query
    assert params is not None
    assert params[0] == "JINA_HTTP_404"
    assert params[1] == "not found"
