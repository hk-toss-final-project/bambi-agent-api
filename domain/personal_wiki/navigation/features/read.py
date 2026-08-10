"""Navigator Wiki Page Version과 Source 읽기 기능."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from psycopg import AsyncConnection

from infrastructure.persistence.api import (
    load_wiki_navigation_pages,
    load_wiki_navigation_sources,
    set_personal_wiki_scope,
)
from shared.wiki_navigation_models import (
    WikiNavigationExcerpt,
    WikiNavigationPage,
    WikiNavigationSource,
)

type DictRow = dict[str, Any]


def _heading_path(metadata: object) -> tuple[str, ...]:
    """Chunk Metadata의 Heading 경로를 문자열 Tuple로 정규화한다."""
    if not isinstance(metadata, Mapping):
        return ()
    raw = metadata.get("heading_path") or ()
    if isinstance(raw, str):
        return (raw,) if raw.strip() else ()
    if isinstance(raw, Sequence):
        return tuple(str(item) for item in raw if str(item).strip())
    return ()


def _build_pages(rows: Sequence[Mapping[str, object]]) -> list[WikiNavigationPage]:
    """Page·Chunk 조회 Row를 Version별 Page 모델로 조립한다."""
    grouped: dict[str, list[Mapping[str, object]]] = {}
    order: list[str] = []
    for row in rows:
        version_id = str(row["document_version_id"])
        if version_id not in grouped:
            grouped[version_id] = []
            order.append(version_id)
        grouped[version_id].append(row)
    pages: list[WikiNavigationPage] = []
    for version_id in order:
        page_rows = grouped[version_id]
        head = page_rows[0]
        excerpts = tuple(
            WikiNavigationExcerpt(
                chunk_id=str(row["chunk_id"]),
                chunk_index=int(row["chunk_index"]),
                content=str(row["chunk_content"]),
                heading_path=_heading_path(row.get("chunk_metadata")),
            )
            for row in page_rows
            if row.get("chunk_id") is not None and row.get("chunk_content")
        )
        aliases = tuple(str(alias) for alias in (head.get("aliases") or ()))
        pages.append(
            WikiNavigationPage(
                document_id=str(head["document_id"]),
                document_version_id=version_id,
                document_kind=str(head["document_kind"]),
                document_key=str(head["document_key"]),
                file_path=str(head["file_path"]),
                title=str(head["title"]),
                aliases=aliases,
                summary=str(head.get("summary") or ""),
                markdown=str(head.get("markdown") or ""),
                version=int(head["version"]),
                updated_at=head["updated_at"],  # type: ignore[arg-type]
                role=str(head["role"]),
                excerpts=excerpts,
            )
        )
    return pages


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wnav_002(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    document_version_ids: Sequence[str] = (),
    document_ids: Sequence[str] = (),
    wiki_version_id: str | None = None,
    max_chunks_per_page: int = 3,
) -> list[WikiNavigationPage]:
    """[WNAV-002] 선택 Version과 순회 Page의 본문·Chunk를 읽는다."""
    if not user_id.strip():
        raise ValueError("WNAV-002에 user_id가 필요합니다.")
    if not 1 <= max_chunks_per_page <= 12:
        raise ValueError("WNAV-002 Page별 Chunk 수는 1에서 12 사이여야 합니다.")
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        rows = await load_wiki_navigation_pages(
            connection,
            user_id=user_id,
            document_version_ids=document_version_ids,
            document_ids=document_ids,
            wiki_version_id=wiki_version_id,
            max_chunks_per_page=max_chunks_per_page,
        )
    return _build_pages(rows)


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wnav_004(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    wiki_document_version_ids: Sequence[str],
) -> list[WikiNavigationSource]:
    """[WNAV-004] Wiki Page의 원본과 사용자 관심 시각을 읽는다."""
    if not user_id.strip():
        raise ValueError("WNAV-004에 user_id가 필요합니다.")
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        rows = await load_wiki_navigation_sources(
            connection,
            user_id=user_id,
            wiki_document_version_ids=wiki_document_version_ids,
        )
    return [
        WikiNavigationSource(
            wiki_document_version_id=str(row["wiki_document_version_id"]),
            source_document_id=str(row["source_document_id"]),
            source_document_version_id=str(row["source_document_version_id"]),
            source_type=str(row["source_type"]),
            title=str(row["title"]),
            url=str(row["url"]) if row.get("url") else None,
            relation_type=str(row["relation_type"]),
            saved_at=row["saved_at"],  # type: ignore[arg-type]
            saved_at_source=str(row["saved_at_source"]),
            stored_at=row["stored_at"],  # type: ignore[arg-type]
            published_at=row.get("published_at"),  # type: ignore[arg-type]
            clipped_on=row.get("clipped_on"),  # type: ignore[arg-type]
        )
        for row in rows
    ]
