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
                {"id": "d1", "canonical_url": "https://a", "current_version": 1},
                {"id": "d2", "canonical_url": "https://b", "current_version": 1},
            ],  # claim
            # d1 성공 저장 경로
            [],  # set_system_job_scope
            [{"current_version": 1, "metadata": {}}],  # Head SELECT
            [{"id": "v2"}],  # INSERT version
            [],  # INSERT chunk
            [],  # UPDATE head
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
    assert results[0]["version"] == 2
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
