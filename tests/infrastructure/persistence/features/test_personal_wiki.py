"""infrastructure/persistence/features/personal_wiki.py의 순수 조회 함수를 검증한다."""

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from infrastructure.persistence.features.personal_wiki import (
    UserSourceDocumentForAgent,
    get_user_source_document_version_for_agent,
)


class _FakeCursor:
    """psycopg Cursor의 fetchone만 흉내 내는 결정적 Test Double."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        """생성 시 전달된 고정 Row를 그대로 반환한다."""
        return self._row


class _FakeConnection:
    """전달된 SQL과 Parameter를 기록하고 고정된 Row를 반환하는 Test Double."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, params: tuple[Any, ...]) -> _FakeCursor:
        """실행된 SQL과 Parameter를 기록한 뒤 고정된 Cursor를 반환한다."""
        self.executed.append((query, params))
        return _FakeCursor(self._row)


def _sample_row() -> dict[str, Any]:
    """user_source_document_versions와 user_source_documents를 결합한 예시 Row."""
    return {
        "source_document_id": "doc-1",
        "user_id": "user-1",
        "namespace_key": "user/user-1",
        "source_type": "web_clipping",
        "canonical_url": "https://example.com/article",
        "source_document_version_id": "version-1",
        "version": 2,
        "title": "제목",
        "author": "저자",
        "published_at": datetime(2026, 7, 1, tzinfo=UTC),
        "clipped_on": date(2026, 7, 2),
        "description": "설명",
        "tags": ["ai", "wiki"],
        "raw_content": "# 본문",
        "content_format": "markdown",
        "object_uri": None,
        "source_metadata": {"clipper": "obsidian"},
    }


def test_get_user_source_document_version_for_agent_maps_row() -> None:
    """조회된 Row를 Agent가 바로 사용할 UserSourceDocumentForAgent로 변환하는지 검증한다."""
    connection = _FakeConnection(_sample_row())

    result = asyncio.run(
        get_user_source_document_version_for_agent(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_version_id="version-1",
        )
    )

    assert result == UserSourceDocumentForAgent(
        source_document_id="doc-1",
        source_document_version_id="version-1",
        user_id="user-1",
        namespace_key="user/user-1",
        source_type="web_clipping",
        canonical_url="https://example.com/article",
        version=2,
        title="제목",
        author="저자",
        published_at=datetime(2026, 7, 1, tzinfo=UTC),
        clipped_on=date(2026, 7, 2),
        description="설명",
        tags=["ai", "wiki"],
        raw_content="# 본문",
        content_format="markdown",
        object_uri=None,
        source_metadata={"clipper": "obsidian"},
    )
    query, params = connection.executed[0]
    assert "agent.user_source_document_versions" in query
    assert "agent.user_source_documents" in query
    assert params == ("version-1", "user-1")


def test_get_user_source_document_version_for_agent_returns_none_when_missing() -> None:
    """일치하는 Row가 없으면 None을 반환하는지 검증한다."""
    connection = _FakeConnection(None)

    result = asyncio.run(
        get_user_source_document_version_for_agent(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_version_id="missing-version",
        )
    )

    assert result is None


def test_get_user_source_document_version_for_agent_defaults_null_collections() -> None:
    """tags와 source_metadata가 NULL로 조회돼도 빈 컬렉션으로 채워지는지 검증한다."""
    row = _sample_row()
    row["tags"] = None
    row["source_metadata"] = None
    connection = _FakeConnection(row)

    result = asyncio.run(
        get_user_source_document_version_for_agent(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_version_id="version-1",
        )
    )

    assert result is not None
    assert result.tags == []
    assert result.source_metadata == {}
