"""infrastructure/persistence/features/personal_wiki.py의 순수 조회 함수를 검증한다."""

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from infrastructure.persistence.features.personal_wiki import (
    UserSourceDocumentForAgent,
    chunk_wiki_markdown,
    get_user_source_document_version_for_agent,
    list_existing_wiki_entries,
    list_existing_wiki_relations,
)


class _FakeCursor:
    """psycopg Cursor의 fetchone만 흉내 내는 결정적 Test Double."""

    def __init__(self, row: dict[str, Any] | list[dict[str, Any]] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        """생성 시 전달된 고정 Row를 그대로 반환한다."""
        if isinstance(self._row, list):
            return self._row[0] if self._row else None
        return self._row

    async def fetchall(self) -> list[dict[str, Any]]:
        """생성 시 전달된 Row를 목록으로 반환한다."""
        if self._row is None:
            return []
        return self._row if isinstance(self._row, list) else [self._row]


class _FakeConnection:
    """전달된 SQL과 Parameter를 기록하고 고정된 Row를 반환하는 Test Double."""

    def __init__(self, row: dict[str, Any] | list[dict[str, Any]] | None) -> None:
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
        "source_event_id": "event-1",
        "version": 2,
        "title": "제목",
        "author": "저자",
        "published_at": datetime(2026, 7, 1, tzinfo=UTC),
        "clipped_on": date(2026, 7, 2),
        "description": "설명",
        "tags": ["ai", "wiki"],
        "raw_content": "# 본문",
        "content_format": "markdown",
        "content_hash": "a" * 64,
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
        source_event_id="event-1",
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
        content_hash="a" * 64,
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


def test_list_existing_wiki_entries_maps_current_versions() -> None:
    """기존 Wiki 최신 Version과 Builder Metadata를 중복 판단 객체로 변환한다."""
    connection = _FakeConnection(
        [
            {
                "document_kind": "entity",
                "document_key": "obsidian",
                "domain": "product",
                "title": "Obsidian",
                "summary": "Markdown 노트 도구",
                "source_metadata": {"aliases": ["옵시디언"]},
            }
        ]
    )

    result = asyncio.run(
        list_existing_wiki_entries(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            document_kind="entity",
        )
    )

    assert result[0].document_key == "obsidian"
    assert result[0].metadata == {"aliases": ["옵시디언"]}
    query, params = connection.executed[0]
    assert "version.version = document.current_version" in query
    assert params == ("user/user-1", "entity")


def test_chunk_wiki_markdown_splits_at_heading_boundaries() -> None:
    """Wiki Markdown을 섹션 Heading 단위의 검색 Chunk로 나눈다."""
    content = "---\ntype: entity\n---\n## Description\n설명\n## Related Entities\n- 관계"

    chunks = chunk_wiki_markdown(content)

    assert chunks == [
        "---\ntype: entity\n---",
        "## Description\n설명",
        "## Related Entities\n- 관계",
    ]


def test_list_existing_wiki_relations_maps_document_keys() -> None:
    """누적 관계 Row를 Schema와 Persistence가 공유하는 관계 계획으로 변환한다."""
    connection = _FakeConnection(
        [
            {
                "source_document_kind": "entity",
                "source_document_key": "obsidian",
                "target_document_kind": "concept",
                "target_document_key": "연결-노트",
                "relation_type": "applies_concept",
                "metadata": {"confidence": 0.9},
            }
        ]
    )

    result = asyncio.run(
        list_existing_wiki_relations(
            connection,  # type: ignore[arg-type]
            namespace_key="user/user-1",
        )
    )

    assert result[0].source_document_key == "obsidian"
    assert result[0].target_document_key == "연결-노트"
    assert result[0].metadata == {"confidence": 0.9}
    assert connection.executed[0][1] == ("user/user-1",)
