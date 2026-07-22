"""infrastructure/persistence/features/personal_wiki.py의 순수 조회 함수를 검증한다."""

import asyncio
import hashlib
from datetime import UTC, date, datetime
from typing import Any

import pytest

from agent.wiki_builder.models import WikiDocumentPlan
from infrastructure.persistence.features.personal_wiki import (
    RegisteredUrlSource,
    SavedUserSourceVersion,
    UserSourceDocumentForAgent,
    _upsert_wiki_document,
    chunk_wiki_markdown,
    get_user_source_document_version_for_agent,
    list_existing_wiki_entries,
    list_existing_wiki_relations,
    mark_url_source_event,
    register_user_url_source,
    save_user_url_document_version,
)


class _FakeCursor:
    """psycopg Cursor의 fetchone만 흉내 내는 결정적 Test Double."""

    def __init__(self, row: dict[str, Any] | list[dict[str, Any]] | None) -> None:
        """조회 시 반환할 고정 Row를 보관한다."""
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
        """고정 Row와 빈 SQL 실행 내역을 초기화한다."""
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


class _SequencedFakeConnection:
    """execute 호출 순서대로 서로 다른 고정 Row를 반환하는 Test Double."""

    def __init__(self, rows: list[dict[str, Any] | list[dict[str, Any]] | None]) -> None:
        """순서대로 반환할 Row와 빈 SQL 실행 내역을 초기화한다."""
        self._rows = list(rows)
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, params: tuple[Any, ...]) -> _FakeCursor:
        """실행 SQL과 Parameter를 기록하고 다음 순서의 Row Cursor를 반환한다."""
        self.executed.append((query, params))
        row = self._rows.pop(0) if self._rows else None
        return _FakeCursor(row)


def _sha256(text: str) -> str:
    """테스트에서 기대 content_hash를 계산한다."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_register_user_url_source_registers_event_and_document() -> None:
    """이벤트·문서 Head를 등록하고 최신 Version 비교 기준을 함께 반환하는지 검증한다."""
    url = "https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
    connection = _SequencedFakeConnection(
        [
            {"id": "event-row-1"},
            {"id": "doc-1"},
            {"version": 2, "content_hash": "b" * 64},
        ]
    )

    result = asyncio.run(
        register_user_url_source(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            url=url,
            source_event_id="user-url-abc",
        )
    )

    assert result == RegisteredUrlSource(
        source_event_row_id="event-row-1",
        source_document_id="doc-1",
        latest_version=2,
        latest_content_hash="b" * 64,
    )
    event_query, event_params = connection.executed[0]
    assert "agent.wiki_source_events" in event_query
    assert "ON CONFLICT (user_id, source_event_id)" in event_query
    assert event_params[:3] == ("user-1", "user-url-abc", url)
    document_query, document_params = connection.executed[1]
    assert "agent.user_source_documents" in document_query
    assert "ON CONFLICT (namespace_key, canonical_url)" in document_query
    assert document_params[:4] == ("user-1", "user/user-1", url, _sha256(url))


def test_register_user_url_source_without_versions_returns_none_baseline() -> None:
    """저장된 Version이 없으면 비교 기준을 None으로 반환하는지 검증한다."""
    connection = _SequencedFakeConnection(
        [{"id": "event-row-1"}, {"id": "doc-1"}, None]
    )

    result = asyncio.run(
        register_user_url_source(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            url="https://dart.fss.or.kr/",
            source_event_id="user-url-dart",
        )
    )

    assert result.latest_version is None
    assert result.latest_content_hash is None


def test_save_user_url_document_version_skips_when_hash_unchanged() -> None:
    """content_hash가 최신 Version과 같으면 새 Version을 만들지 않는지 검증한다."""
    raw_content = "# 코스피\n\n지수 요약"
    connection = _SequencedFakeConnection(
        [{"version": 3, "content_hash": _sha256(raw_content)}]
    )

    result = asyncio.run(
        save_user_url_document_version(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_id="doc-1",
            source_event_row_id="event-row-1",
            title="KOSPI",
            raw_content=raw_content,
        )
    )

    assert result is None
    assert len(connection.executed) == 1


def test_save_user_url_document_version_creates_first_version() -> None:
    """첫 수집이면 version 1을 만들고 문서 Head hash를 갱신하는지 검증한다."""
    raw_content = "# 코스피\n\n지수 요약"
    connection = _SequencedFakeConnection([None, {"id": "version-row-1"}, None])

    result = asyncio.run(
        save_user_url_document_version(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_id="doc-1",
            source_event_row_id="event-row-1",
            title="KOSPI",
            raw_content=raw_content,
            resolved_url="https://finance.naver.com/resolved",
        )
    )

    assert result == SavedUserSourceVersion(
        source_version_id="version-row-1",
        version=1,
        content_hash=_sha256(raw_content),
    )
    insert_query, insert_params = connection.executed[1]
    assert "agent.user_source_document_versions" in insert_query
    assert insert_params[0] == "doc-1"
    assert insert_params[3] == 1
    assert insert_params[4] == "KOSPI"
    update_query, update_params = connection.executed[2]
    assert "UPDATE agent.user_source_documents" in update_query
    assert update_params == (1, _sha256(raw_content), "doc-1")


def test_save_user_url_document_version_increments_version_on_change() -> None:
    """내용이 바뀌면 최신 Version + 1로 새 스냅샷을 저장하는지 검증한다."""
    connection = _SequencedFakeConnection(
        [
            {"version": 2, "content_hash": "c" * 64},
            {"id": "version-row-3"},
            None,
        ]
    )

    result = asyncio.run(
        save_user_url_document_version(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_id="doc-1",
            source_event_row_id=None,
            title="갱신된 제목",
            raw_content="새 본문",
        )
    )

    assert result is not None
    assert result.version == 3


def test_mark_url_source_event_rejects_unknown_status() -> None:
    """허용되지 않은 이벤트 상태는 ValueError를 발생시키는지 검증한다."""
    connection = _SequencedFakeConnection([])

    with pytest.raises(ValueError):
        asyncio.run(
            mark_url_source_event(
                connection,  # type: ignore[arg-type]
                source_event_row_id="event-row-1",
                status="queued",
            )
        )
    assert connection.executed == []


def test_mark_url_source_event_records_failure_details() -> None:
    """실패 상태가 오류 코드·메시지와 함께 이벤트 Row에 기록되는지 검증한다."""
    connection = _SequencedFakeConnection([None])

    asyncio.run(
        mark_url_source_event(
            connection,  # type: ignore[arg-type]
            source_event_row_id="event-row-1",
            status="failed",
            error_code="http_451",
            error_message="차단된 URL",
        )
    )

    query, params = connection.executed[0]
    assert "UPDATE agent.wiki_source_events" in query
    assert params == (
        "failed",
        "http_451",
        "차단된 URL",
        "failed",
        "failed",
        "event-row-1",
    )


class _SequencedConnection:
    """호출 순서별 응답 목록을 돌려주는 Connection Test Double."""

    def __init__(self, responses: list[dict[str, Any] | list[dict[str, Any]] | None]) -> None:
        """순서별 응답과 빈 SQL 실행 내역을 초기화한다."""
        self._responses = responses
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, params: tuple[Any, ...]) -> _FakeCursor:
        """실행된 SQL을 기록하고 순서에 맞는 고정 Cursor를 반환한다."""
        self.executed.append((query, params))
        row = self._responses.pop(0) if self._responses else None
        return _FakeCursor(row)


def _sample_source() -> UserSourceDocumentForAgent:
    """Wiki Build 대상 사용자 원본 Version 예시."""
    return UserSourceDocumentForAgent(
        source_document_id="doc-1",
        source_document_version_id="version-1",
        source_event_id="event-1",
        user_id="user-1",
        namespace_key="user/user-1",
        source_type="url",
        canonical_url="https://example.com",
        version=1,
        title="원본",
        author=None,
        published_at=None,
        clipped_on=None,
        description=None,
    )


def _sample_plan_document() -> WikiDocumentPlan:
    """저장 예정인 entity 문서 계획 예시."""
    return WikiDocumentPlan(
        document_kind="entity",
        document_key="postgresql",
        file_path="entities/postgresql.md",
        domain=None,
        title="PostgreSQL",
        summary="요약",
        normalized_content="## Description\n동일한 본문",
        action="create",
    )


def test_upsert_wiki_document_reuses_existing_document_with_same_content() -> None:
    """새 Head의 내용이 기존 문서와 동일하면 INSERT 없이 재사용한다(PWIKI-008)."""
    duplicate = {
        "id": "doc-existing",
        "document_kind": "entity",
        "document_key": "postgres",
        "file_path": "entities/postgres.md",
        "current_version": 2,
    }
    connection = _SequencedConnection(
        [None, duplicate, {"id": "version-existing"}, None]
    )

    persisted, changed = asyncio.run(
        _upsert_wiki_document(
            connection,  # type: ignore[arg-type]
            source=_sample_source(),
            document=_sample_plan_document(),
            job_id="job-1",
        )
    )

    assert changed is False
    assert persisted.action == "deduplicated"
    assert persisted.document_id == "doc-existing"
    assert persisted.document_key == "postgres"
    assert persisted.version == 2
    assert not any(
        "INSERT INTO agent.wiki_documents" in query
        for query, _ in connection.executed
    )


def test_upsert_wiki_document_skips_version_when_update_duplicates_other_document() -> None:
    """갱신 내용이 다른 문서와 동일하면 새 Version을 만들지 않는다(PWIKI-008)."""
    head = {"id": "doc-head", "current_version": 3, "content_hash": "b" * 64}
    duplicate = {
        "id": "doc-existing",
        "document_kind": "entity",
        "document_key": "postgres",
        "file_path": "entities/postgres.md",
        "current_version": 2,
    }
    connection = _SequencedConnection(
        [head, duplicate, {"id": "version-head-3"}, None]
    )

    persisted, changed = asyncio.run(
        _upsert_wiki_document(
            connection,  # type: ignore[arg-type]
            source=_sample_source(),
            document=_sample_plan_document(),
            job_id="job-1",
        )
    )

    assert changed is False
    assert persisted.action == "deduplicated"
    assert persisted.document_id == "doc-head"
    assert persisted.version == 3
    assert not any(
        "INSERT INTO agent.wiki_document_versions" in query
        for query, _ in connection.executed
    )
    assert not any(
        "UPDATE agent.wiki_documents" in query for query, _ in connection.executed
    )
