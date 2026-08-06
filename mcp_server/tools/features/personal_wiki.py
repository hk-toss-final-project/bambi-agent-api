"""읽기 전용 Personal Wiki MCP 검색·문서 조회 기능."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field

from shared.contracts import FeatureRequest, FeatureResult


class PersonalWikiMcpReader(Protocol):
    """Personal Wiki MCP 도구가 사용하는 읽기 저장소 계약."""

    async def search_documents(
        self, user_id: str, *, query: str, limit: int
    ) -> Sequence[Mapping[str, object]]:
        """사용자 Namespace에서 질의와 일치하는 문서를 검색한다."""
        ...

    async def get_document(
        self, user_id: str, document_id: str
    ) -> Mapping[str, object] | None:
        """사용자 Namespace의 문서 상세를 조회한다."""
        ...


class WikiSearchResult(BaseModel):
    """LLM이 후속 fetch 대상을 고를 수 있는 Wiki 검색 결과."""

    id: str
    title: str
    url: str
    text: str
    metadata: dict[str, object] = Field(default_factory=dict)


class WikiSearchOutput(BaseModel):
    """표준 search MCP Tool의 구조화된 결과."""

    results: list[WikiSearchResult] = Field(default_factory=list)


class WikiFetchOutput(BaseModel):
    """표준 fetch MCP Tool의 문서 본문과 출처 Metadata."""

    id: str
    title: str
    text: str
    url: str
    metadata: dict[str, object] = Field(default_factory=dict)


async def mcptool_001(
    reader: PersonalWikiMcpReader,
    *,
    user_id: str,
    query: str,
    limit: int,
) -> WikiSearchOutput:
    """[MCPTOOL-001] Personal Wiki 검색.

    승인된 사용자의 개인 Wiki만 검색하며 일치하지 않으면 빈 결과를 반환한다.
    """
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("검색어를 입력해야 합니다.")
    rows = await reader.search_documents(
        user_id,
        query=normalized_query,
        limit=min(20, max(1, limit)),
    )
    return WikiSearchOutput(
        results=[
            WikiSearchResult(
                id=str(row["document_id"]),
                title=str(row["title"]),
                url=f"bambi://wiki/documents/{row['document_id']}",
                text=str(row.get("summary") or ""),
                metadata={
                    "document_kind": str(row["document_kind"]),
                    "updated_at": _serialize_datetime(row.get("updated_at")),
                },
            )
            for row in rows
        ]
    )


async def mcptool_002(
    reader: PersonalWikiMcpReader, *, user_id: str, document_id: str
) -> WikiFetchOutput:
    """[MCPTOOL-002] Personal Wiki 문서 조회.

    개인 Wiki의 특정 문서를 조회한다.
    """
    row = await reader.get_document(user_id, document_id)
    if row is None:
        raise ValueError("Personal Wiki 문서를 찾을 수 없습니다.")
    sources = row.get("sources")
    source_items = list(sources) if isinstance(sources, list) else []
    source_urls = [
        str(source["canonical_url"])
        for source in source_items
        if isinstance(source, Mapping) and source.get("canonical_url")
    ]
    return WikiFetchOutput(
        id=str(row["document_id"]),
        title=str(row["title"]),
        text=str(row.get("markdown") or ""),
        url=f"bambi://wiki/documents/{row['document_id']}",
        metadata={
            "document_kind": str(row["document_kind"]),
            "summary": str(row.get("summary") or ""),
            "updated_at": _serialize_datetime(row.get("updated_at")),
            "source_urls": source_urls,
        },
    )


def _serialize_datetime(value: object) -> str | None:
    """MCP Metadata의 날짜 값을 ISO 8601 문자열로 정규화한다."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


async def mcptool_003(request: FeatureRequest) -> FeatureResult:
    """[MCPTOOL-003] Personal Wiki Source 추가.

    사용자 승인 하에 Wiki Source를 추가한다.
    """
    raise NotImplementedError("[MCPTOOL-003] 기능 구현이 필요합니다.")
