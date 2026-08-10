"""Personal Wiki MCP search·fetch·add_source·구조화 저장 도구의 계약을 검증한다."""

import asyncio
from datetime import UTC, datetime

import pytest

from mcp_server.tools.api import (
    ClaudeConceptInput,
    ClaudeEntityInput,
    ClaudeRelationInput,
    mcptool_001,
    mcptool_002,
    mcptool_003,
    mcptool_013,
    mcptool_014,
)


class _FakeWikiReader:
    """요청 사용자와 검색어를 기록하는 Personal Wiki 읽기 대역."""

    def __init__(self) -> None:
        """호출 기록을 초기화한다."""
        self.calls: list[tuple[str, str]] = []

    async def search_documents(
        self, user_id: str, *, query: str, limit: int
    ) -> list[dict[str, object]]:
        """알려진 검색어에만 Wiki 문서 요약을 반환한다."""
        self.calls.append(("search", user_id))
        if query != "Obsidian":
            return []
        return [
            {
                "document_id": "document-1",
                "document_kind": "entity",
                "title": "Obsidian",
                "summary": "연결형 노트 도구",
                "updated_at": datetime(2026, 8, 6, tzinfo=UTC),
            }
        ][:limit]

    async def get_document(
        self, user_id: str, document_id: str
    ) -> dict[str, object] | None:
        """인증 사용자 42의 알려진 문서만 반환한다."""
        self.calls.append(("fetch", user_id))
        if user_id != "42" or document_id != "document-1":
            return None
        return {
            "document_id": document_id,
            "document_kind": "entity",
            "title": "Obsidian",
            "summary": "연결형 노트 도구",
            "markdown": "# Obsidian\n\n연결형 노트 도구",
            "updated_at": datetime(2026, 8, 6, tzinfo=UTC),
            "sources": [{"canonical_url": "https://obsidian.md"}],
        }


class _FakeWikiWriter:
    """요청 사용자와 저장 인자를 기록하는 Personal Wiki 쓰기 대역."""

    def __init__(self) -> None:
        """호출 기록을 초기화한다."""
        self.calls: list[dict[str, object]] = []

    async def add_source(
        self,
        user_id: str,
        *,
        title: str,
        content: str,
        tags: list[str],
        memo: str | None,
        occurred_at: datetime | None,
    ) -> dict[str, object]:
        """호출 인자를 기록하고 고정된 저장 결과를 반환한다."""
        self.calls.append(
            {
                "user_id": user_id,
                "title": title,
                "content": content,
                "tags": tags,
                "memo": memo,
            }
        )
        return {
            "source_document_id": "source-1",
            "source_document_version_id": "source-version-1",
            "source_version": 1,
        }


def test_search_returns_only_matching_personal_wiki_documents() -> None:
    """검색 결과가 인증 사용자 범위이며 무관한 질의에는 fallback을 반환하지 않는다."""
    asyncio.run(_assert_search_returns_only_matches())


async def _assert_search_returns_only_matches() -> None:
    """검색 도구의 일치·불일치 응답을 검증한다."""
    reader = _FakeWikiReader()
    found = await mcptool_001(reader, user_id="42", query="Obsidian", limit=10)
    missing = await mcptool_001(reader, user_id="42", query="unrelated", limit=10)

    assert found.results[0].id == "document-1"
    assert found.results[0].url == "bambi://wiki/documents/document-1"
    assert missing.results == []
    assert reader.calls == [("search", "42"), ("search", "42")]


def test_fetch_returns_markdown_and_hides_other_user_document() -> None:
    """fetch가 인증 사용자 문서만 Markdown과 출처 Metadata로 반환한다."""
    asyncio.run(_assert_fetch_is_user_scoped())


async def _assert_fetch_is_user_scoped() -> None:
    """문서 조회 도구의 사용자 격리 시나리오를 검증한다."""
    reader = _FakeWikiReader()
    fetched = await mcptool_002(reader, user_id="42", document_id="document-1")

    assert fetched.text.startswith("# Obsidian")
    assert fetched.metadata["source_urls"] == ["https://obsidian.md"]
    try:
        await mcptool_002(reader, user_id="99", document_id="document-1")
    except ValueError as error:
        assert "찾을 수 없습니다" in str(error)
    else:
        raise AssertionError("다른 사용자 문서 조회가 거부되어야 합니다.")


def test_add_source_persists_trimmed_content_for_authenticated_user() -> None:
    """add_source가 인증 사용자 범위로 다듬어진 제목·본문을 저장한다."""
    asyncio.run(_assert_add_source_persists())


async def _assert_add_source_persists() -> None:
    """Source 추가 도구의 성공 경로를 검증한다."""
    writer = _FakeWikiWriter()
    result = await mcptool_003(
        writer,
        user_id="42",
        title="  제목  ",
        content="  본문 내용  ",
        tags=["ai"],
        memo="메모",
        occurred_at=None,
    )

    assert result.source_document_id == "source-1"
    assert result.source_document_version_id == "source-version-1"
    assert result.source_version == 1
    assert writer.calls == [
        {
            "user_id": "42",
            "title": "제목",
            "content": "본문 내용",
            "tags": ["ai"],
            "memo": "메모",
        }
    ]


def test_add_source_rejects_blank_title_and_content() -> None:
    """add_source가 공백뿐인 제목·본문을 저장 전에 거부한다."""
    asyncio.run(_assert_add_source_rejects_blank_input())


async def _assert_add_source_rejects_blank_input() -> None:
    """공백 제목·본문에 대한 도구 유효성 검증을 실행한다."""
    writer = _FakeWikiWriter()

    with pytest.raises(ValueError):
        await mcptool_003(
            writer,
            user_id="42",
            title="   ",
            content="본문",
            occurred_at=None,
        )
    with pytest.raises(ValueError):
        await mcptool_003(
            writer,
            user_id="42",
            title="제목",
            content="   ",
            occurred_at=None,
        )
    assert writer.calls == []


class _FakeEntryWriter:
    """전달된 분류 결과를 기록하는 구조화 문서 저장 대역."""

    def __init__(self) -> None:
        """호출 기록을 초기화한다."""
        self.calls: list[dict[str, object]] = []

    async def save_structured_entry(
        self,
        user_id: str,
        *,
        source_document_version_id: str,
        classification: object,
        model: str,
    ) -> dict[str, object]:
        """호출 인자를 기록하고 고정된 저장 결과를 반환한다."""
        self.calls.append(
            {
                "user_id": user_id,
                "source_document_version_id": source_document_version_id,
                "classification": classification,
                "model": model,
            }
        )
        return {
            "wiki_version_id": "wiki-version-1",
            "affected_document_count": 2,
            "quality_passed": True,
            "quality_warning_count": 1,
        }


def test_save_structured_entry_builds_classification_and_persists() -> None:
    """save_structured_entry가 입력을 WikiClassification으로 변환해 저장한다."""
    asyncio.run(_assert_save_structured_entry_persists())


async def _assert_save_structured_entry_persists() -> None:
    """구조화 문서 저장 도구의 성공 경로를 검증한다."""
    writer = _FakeEntryWriter()
    result = await mcptool_013(
        writer,
        user_id="42",
        source_document_version_id="source-version-1",
        entities=[ClaudeEntityInput(name="Obsidian", subtype="product", description="노트 도구")],
        concepts=[ClaudeConceptInput(title="PKM", subtype="method", definition="지식 관리 방법론")],
        relations=[
            ClaudeRelationInput(
                source_name="Obsidian",
                source_kind="entity",
                target_name="PKM",
                target_kind="concept",
                relation_type="instance_of",
                evidence="Obsidian은 PKM 도구다.",
            )
        ],
        source_summary="요약",
    )

    assert result.wiki_version_id == "wiki-version-1"
    assert result.affected_document_count == 2
    assert result.quality_passed is True
    assert result.quality_warning_count == 1
    assert len(writer.calls) == 1
    call = writer.calls[0]
    assert call["user_id"] == "42"
    assert call["source_document_version_id"] == "source-version-1"
    classification = call["classification"]
    assert classification.entities[0].name == "Obsidian"
    assert classification.concepts[0].title == "PKM"
    assert classification.relations[0].relation_type == "instance_of"


def test_save_structured_entry_rejects_missing_nodes_and_bad_subtype() -> None:
    """entity·concept이 하나도 없거나 서브타입이 허용 밖이면 거부한다."""
    asyncio.run(_assert_save_structured_entry_rejects_invalid_input())


async def _assert_save_structured_entry_rejects_invalid_input() -> None:
    """구조화 문서 저장 도구의 유효성 검증 경로를 실행한다."""
    writer = _FakeEntryWriter()

    with pytest.raises(ValueError):
        await mcptool_013(writer, user_id="42", source_document_version_id="source-version-1")
    with pytest.raises(ValueError):
        await mcptool_013(
            writer,
            user_id="42",
            source_document_version_id="source-version-1",
            entities=[ClaudeEntityInput(name="X", subtype="not-a-real-subtype")],
        )
    assert writer.calls == []


class _FakeRebuildTrigger:
    """요청 인자를 기록하는 재빌드 트리거 대역."""

    def __init__(self) -> None:
        """호출 기록을 초기화한다."""
        self.calls: list[dict[str, object]] = []

    async def trigger_rebuild(
        self, user_id: str, *, source_document_version_id: str, request_id: str | None
    ) -> dict[str, object]:
        """호출 인자를 기록하고 고정된 Job 결과를 반환한다."""
        self.calls.append(
            {
                "user_id": user_id,
                "source_document_version_id": source_document_version_id,
                "request_id": request_id,
            }
        )
        return {"job_id": "wiki-job-1", "job_created": True}


def test_trigger_rebuild_forwards_request_to_writer() -> None:
    """trigger_rebuild가 인증 사용자와 원본 Version을 그대로 전달하는지 검증한다."""
    asyncio.run(_assert_trigger_rebuild_forwards_request())


async def _assert_trigger_rebuild_forwards_request() -> None:
    """재빌드 트리거 도구의 성공 경로를 검증한다."""
    trigger = _FakeRebuildTrigger()
    result = await mcptool_014(
        trigger,
        user_id="42",
        source_document_version_id="source-version-1",
        request_id="request-1",
    )

    assert result.job_id == "wiki-job-1"
    assert result.job_created is True
    assert trigger.calls == [
        {
            "user_id": "42",
            "source_document_version_id": "source-version-1",
            "request_id": "request-1",
        }
    ]
