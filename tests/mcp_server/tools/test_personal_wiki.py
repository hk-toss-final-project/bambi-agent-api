"""Personal Wiki MCP search·fetch 도구의 사용자 격리와 응답 계약을 검증한다."""

import asyncio
from datetime import UTC, datetime

from mcp_server.tools.api import mcptool_001, mcptool_002


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
