"""개인 Wiki 문서 삭제 반영 SQL을 검증한다."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from infrastructure.persistence.features.wiki_deletion import (
    WikiDocumentNotFoundError,
    delete_wiki_document_and_record_event,
)


class _FakeCursor:
    """실행 순서대로 준비된 Row를 반환하는 Cursor Test Double."""

    def __init__(self, row: Any) -> None:
        """이 실행에 대응하는 고정 Row를 보관한다."""
        self._row = row

    async def fetchone(self) -> Any:
        """준비된 Row 하나를 반환한다."""
        if isinstance(self._row, list):
            return self._row[0] if self._row else None
        return self._row

    async def fetchall(self) -> list[Any]:
        """준비된 Row 목록을 반환한다."""
        if self._row is None:
            return []
        return self._row if isinstance(self._row, list) else [self._row]


class _FakeConnection:
    """SQL 실행 내역을 기록하고 실행 순서별 Row를 반환하는 Connection Test Double."""

    def __init__(self, rows: list[Any]) -> None:
        """실행 순서별 반환 Row 큐와 실행 기록을 초기화한다."""
        self._rows = list(rows)
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.transactions = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """열린 Transaction 수를 세는 문맥을 제공한다."""
        self.transactions += 1
        yield

    async def execute(self, query: str, params: tuple[Any, ...] = ()) -> _FakeCursor:
        """SQL과 Parameter를 기록하고 다음 준비 Row를 반환한다."""
        self.executed.append((query, params))
        return _FakeCursor(self._rows.pop(0) if self._rows else None)


def test_delete_soft_deletes_document_and_chunks_in_one_transaction() -> None:
    """이벤트 기록·soft-delete·Chunk 제외가 한 Transaction에서 실행되는지 검증한다."""
    connection = _FakeConnection(
        [
            None,  # scope
            {
                "id": "document-1",
                "document_kind": "entity",
                "document_key": "obsidian",
                "deleted_at": None,
            },
            None,  # event insert
            None,  # document update
            [{"id": "chunk-1"}, {"id": "chunk-2"}],
        ]
    )

    result = asyncio.run(
        delete_wiki_document_and_record_event(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            document_id="document-1",
            source_event_id="delete-1",
            occurred_at=None,
            memo="정리",
        )
    )

    assert connection.transactions == 1
    assert result["already_deleted"] is False
    assert result["unsearchable_chunk_count"] == 2
    executed_sql = [query for query, _ in connection.executed]
    assert any("'delete'" in query for query in executed_sql)
    assert any("SET status = 'deleted'" in query for query in executed_sql)
    assert any("SET is_searchable = false" in query for query in executed_sql)


def test_delete_is_idempotent_for_already_deleted_document() -> None:
    """이미 삭제된 문서 재요청이 갱신 없이 멱등 결과를 반환하는지 검증한다."""
    connection = _FakeConnection(
        [
            None,  # scope
            {
                "id": "document-1",
                "document_kind": "entity",
                "document_key": "obsidian",
                "deleted_at": datetime(2026, 7, 20, tzinfo=UTC),
            },
            None,  # event insert
        ]
    )

    result = asyncio.run(
        delete_wiki_document_and_record_event(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            document_id="document-1",
            source_event_id="delete-2",
            occurred_at=None,
            memo=None,
        )
    )

    assert result["already_deleted"] is True
    assert result["unsearchable_chunk_count"] == 0
    executed_sql = [query for query, _ in connection.executed]
    assert not any("SET status = 'deleted'" in query for query in executed_sql)


def test_delete_raises_for_unknown_document() -> None:
    """사용자 Namespace에 없는 문서 삭제가 도메인 오류를 던지는지 검증한다."""
    connection = _FakeConnection([None, None])

    with pytest.raises(WikiDocumentNotFoundError):
        asyncio.run(
            delete_wiki_document_and_record_event(
                connection,  # type: ignore[arg-type]
                user_id="user-1",
                document_id="missing",
                source_event_id="delete-x",
                occurred_at=None,
                memo=None,
            )
        )
