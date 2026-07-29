"""Global 뉴스 본문 수집 Worker(Jina)의 저장·실패 격리를 검증한다.

실제 DB·네트워크 없이 Connection과 URL 수집기를 대역으로 주입해, 본문 저장과
문서별 실패 격리 흐름을 확인한다.
"""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any

import pytest

import workers.features.global_content_fetcher as fetcher
from infrastructure.sources.connectors.api import JinaReadError, JinaReadResult


class _FakeCursor:
    """순서별 Row를 반환하는 Cursor Test Double."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        """첫 번째 Row나 None을 반환한다."""
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        """전체 Row 목록을 반환한다."""
        return self._rows


class _FakeConnection:
    """execute 순서별 응답과 transaction·close를 흉내 내는 Connection 대역."""

    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        self._responses = responses
        self.executed: list[str] = []
        self.closed = False

    async def execute(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> _FakeCursor:
        """SQL을 기록하고 순서별 Cursor를 반환한다."""
        self.executed.append(query)
        rows = self._responses.pop(0) if self._responses else []
        return _FakeCursor(rows)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """psycopg transaction 문맥을 흉내 낸다."""
        yield

    async def close(self) -> None:
        """연결 종료를 기록한다."""
        self.closed = True


def _patch_connection(
    monkeypatch: pytest.MonkeyPatch, connection: _FakeConnection
) -> None:
    """AsyncConnection.connect가 주어진 대역 연결을 반환하도록 교체한다."""

    class _FakeAsyncConnection:
        @classmethod
        async def connect(cls, *args: Any, **kwargs: Any) -> _FakeConnection:
            """대역 연결을 반환한다."""
            return connection

    monkeypatch.setattr(fetcher, "AsyncConnection", _FakeAsyncConnection)


def test_content_fetch_saves_body_and_isolates_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """성공 URL은 본문을 저장하고 실패 URL은 failed로 격리하는지 검증한다."""
    connection = _FakeConnection(
        [
            [],  # set_system_job_scope (claim)
            [
                {"id": "d1", "canonical_url": "https://a"},
                {"id": "d2", "canonical_url": "https://b"},
            ],  # claim
            # d1 성공 저장 경로
            [],  # set_system_job_scope
            [{"id": "d1"}],  # UPDATE 캐시 문서 → fetched
            # d2 실패 경로
            [],  # set_system_job_scope
            [],  # mark_failed UPDATE
        ]
    )
    _patch_connection(monkeypatch, connection)

    def fake_fetcher(url: str) -> JinaReadResult:
        """성공 URL은 본문을, 실패 URL은 Jina 오류를 발생시킨다."""
        if url == "https://b":
            raise JinaReadError("http_404", "not found")
        return JinaReadResult(
            requested_url=url,
            resolved_url="https://a/final",
            title="본문 제목",
            published_time="2026-07-20T00:00:00Z",
            markdown="# 전체 본문",
        )

    results = asyncio.run(
        fetcher.run_global_content_fetch_batch(
            database_url="postgresql://fake",
            limit=5,
            url_fetcher=fake_fetcher,
        )
    )

    assert connection.closed is True
    assert results[0]["status"] == "completed"
    assert results[0]["document_id"] == "d1"
    assert results[0]["content_status"] == "fetched"
    assert results[1]["status"] == "failed"
    assert results[1]["error_code"] == "JINA_HTTP_404"


def test_content_fetch_returns_empty_when_no_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """점유할 pending 문서가 없으면 빈 결과를 반환하는지 검증한다."""
    connection = _FakeConnection(
        [
            [],  # set_system_job_scope
            [],  # claim → 없음
        ]
    )
    _patch_connection(monkeypatch, connection)

    results = asyncio.run(
        fetcher.run_global_content_fetch_batch(
            database_url="postgresql://fake",
            limit=5,
            url_fetcher=lambda _: JinaReadResult(
                requested_url="",
                resolved_url="",
                title="",
                published_time=None,
                markdown="x",
            ),
        )
    )

    assert results == []


def test_youtube_document_uses_transcript_as_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """YouTube 문서는 Jina 대신 자막을 본문으로 저장하는지 검증한다."""
    connection = _FakeConnection(
        [
            [],  # set_system_job_scope (claim)
            [
                {
                    "id": "y1",
                    "canonical_url": "https://www.youtube.com/watch?v=abc12345678",
                    "provider": "youtube",
                }
            ],  # claim
            [],  # set_system_job_scope (저장)
            [{"id": "y1"}],  # UPDATE 캐시 문서 → fetched
        ]
    )
    _patch_connection(monkeypatch, connection)

    def fail_jina(url: str) -> JinaReadResult:
        """YouTube 문서에는 Jina를 쓰지 않아야 한다."""
        raise AssertionError("YouTube 문서에 Jina Reader를 호출했습니다.")

    results = asyncio.run(
        fetcher.run_global_content_fetch_batch(
            database_url="postgresql://fake",
            limit=5,
            url_fetcher=fail_jina,
            # 최소 자막 길이 게이트를 넘도록 본문 분량을 충분히 준다.
            transcript_fetcher=lambda video_id: f"{video_id} 자막 본문 " * 100,
        )
    )

    assert results[0]["status"] == "completed"
    assert results[0]["content_status"] == "fetched"
    # 자막 저장은 제목을 주지 않으므로, 수집 때 저장한 영상 제목이 지워지면 안 된다.
    saved_sql = next(
        sql
        for sql in connection.executed
        if "UPDATE agent.global_source_documents" in sql and "fetched" in sql
    )
    assert "COALESCE(%s, title)" in saved_sql


def test_youtube_document_without_transcript_is_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """자막이 없는 영상은 빈 본문을 저장하지 않고 실패로 남기는지 검증한다."""
    connection = _FakeConnection(
        [
            [],  # set_system_job_scope (claim)
            [
                {
                    "id": "y2",
                    "canonical_url": "https://www.youtube.com/watch?v=abc12345678",
                    "provider": "youtube",
                }
            ],  # claim
            [],  # set_system_job_scope (실패 표시)
            [],  # mark_failed UPDATE
        ]
    )
    _patch_connection(monkeypatch, connection)

    results = asyncio.run(
        fetcher.run_global_content_fetch_batch(
            database_url="postgresql://fake",
            limit=5,
            url_fetcher=lambda _: JinaReadResult(
                requested_url="",
                resolved_url="",
                title="",
                published_time=None,
                markdown="x",
            ),
            transcript_fetcher=lambda _: None,
        )
    )

    assert results[0]["status"] == "failed"
    assert results[0]["error_code"] == "YOUTUBE_NO_TRANSCRIPT"


def test_youtube_document_with_too_short_transcript_is_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """자막이 최소 길이에 못 미치면 본문으로 저장하지 않고 실패로 남긴다.

    영상 길이가 아니라 자막 길이로 판정한다 — 우리는 영상을 자막으로만 읽으므로
    "읽을 게 있는가"가 실제 기준이다.
    """
    connection = _FakeConnection(
        [
            [],  # set_system_job_scope (claim)
            [
                {
                    "id": "y3",
                    "canonical_url": "https://www.youtube.com/watch?v=abc12345678",
                    "provider": "youtube",
                }
            ],  # claim
            [],  # set_system_job_scope (실패 표시)
            [],  # mark_failed UPDATE
        ]
    )
    _patch_connection(monkeypatch, connection)

    results = asyncio.run(
        fetcher.run_global_content_fetch_batch(
            database_url="postgresql://fake",
            limit=5,
            url_fetcher=lambda _: JinaReadResult(
                requested_url="",
                resolved_url="",
                title="",
                published_time=None,
                markdown="x",
            ),
            transcript_fetcher=lambda _: "속보입니다",
        )
    )

    assert results[0]["status"] == "failed"
    assert results[0]["error_code"] == "YOUTUBE_TRANSCRIPT_TOO_SHORT"


def test_youtube_minimum_transcript_length_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """최소 자막 길이는 환경변수로 조정하고, 값이 잘못되면 기본값을 쓴다."""
    monkeypatch.setenv("YOUTUBE_MIN_TRANSCRIPT_CHARS", "120")
    assert fetcher._min_transcript_chars() == 120

    monkeypatch.setenv("YOUTUBE_MIN_TRANSCRIPT_CHARS", "숫자아님")
    assert fetcher._min_transcript_chars() == fetcher.DEFAULT_MIN_TRANSCRIPT_CHARS

    monkeypatch.delenv("YOUTUBE_MIN_TRANSCRIPT_CHARS")
    assert fetcher._min_transcript_chars() == fetcher.DEFAULT_MIN_TRANSCRIPT_CHARS
