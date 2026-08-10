"""Navigator Logical Index 후보 Locate 기능."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection

from infrastructure.persistence.api import (
    load_wiki_navigation_keyword_candidates,
    load_wiki_navigation_vector_candidates,
    set_personal_wiki_scope,
)
from shared.wiki_navigation_models import WikiNavigationCandidate

logger = logging.getLogger("domain.personal_wiki.navigation.locate")

type DictRow = dict[str, Any]

DEFAULT_NAVIGATION_CANDIDATE_LIMIT = 30
MAX_NAVIGATION_CANDIDATE_LIMIT = 30
NAVIGATION_RRF_K = 60
DEFAULT_WIKI_EMBEDDING_MODEL = "text-embedding-3-small"


def _aliases(row: Mapping[str, object]) -> tuple[str, ...]:
    """조회 Row의 별칭 값을 문자열 Tuple로 정규화한다."""
    raw = row.get("aliases") or ()
    return tuple(str(alias) for alias in raw if str(alias).strip())


def _candidate_key(row: Mapping[str, object]) -> str:
    """후보 RRF 병합에 사용할 Page Version 식별자를 반환한다."""
    return str(row["document_version_id"])


def _candidate_from_rows(
    row: Mapping[str, object],
    *,
    keyword_rank: int | None,
    vector_rank: int | None,
    rrf_score: float,
) -> WikiNavigationCandidate:
    """Keyword·Vector Row를 공개 Navigator 후보 모델로 변환한다."""
    return WikiNavigationCandidate(
        document_id=str(row["document_id"]),
        document_version_id=str(row["document_version_id"]),
        document_kind=str(row["document_kind"]),
        document_key=str(row["document_key"]),
        file_path=str(row["file_path"]),
        title=str(row["title"]),
        aliases=_aliases(row),
        summary=str(row.get("summary") or ""),
        updated_at=row["updated_at"],  # type: ignore[arg-type]
        exact_match=bool(row.get("exact_match")),
        alias_match=bool(row.get("alias_match")),
        keyword_rank=keyword_rank,
        vector_rank=vector_rank,
        rrf_score=rrf_score,
    )


def _merge_candidate_rankings(
    keyword_rows: Sequence[Mapping[str, object]],
    vector_rows: Sequence[Mapping[str, object]],
    *,
    limit: int,
) -> list[WikiNavigationCandidate]:
    """Page degree 없이 Keyword·Vector 순위를 결정적 RRF로 결합한다."""
    rows: dict[str, Mapping[str, object]] = {}
    keyword_ranks: dict[str, int] = {}
    vector_ranks: dict[str, int] = {}
    fused_scores: dict[str, float] = {}
    for rank, row in enumerate(keyword_rows, start=1):
        key = _candidate_key(row)
        rows.setdefault(key, row)
        keyword_ranks.setdefault(key, rank)
        fused_scores[key] = fused_scores.get(key, 0.0) + 1.0 / (
            NAVIGATION_RRF_K + rank
        )
    for rank, row in enumerate(vector_rows, start=1):
        key = _candidate_key(row)
        rows.setdefault(key, row)
        vector_ranks.setdefault(key, rank)
        fused_scores[key] = fused_scores.get(key, 0.0) + 1.0 / (
            NAVIGATION_RRF_K + rank
        )
    ordered = sorted(
        rows,
        key=lambda key: (
            -int(bool(rows[key].get("exact_match"))),
            -int(bool(rows[key].get("alias_match"))),
            -fused_scores[key],
            keyword_ranks.get(key, 10**9),
            vector_ranks.get(key, 10**9),
            str(rows[key].get("title") or ""),
            key,
        ),
    )
    return [
        _candidate_from_rows(
            rows[key],
            keyword_rank=keyword_ranks.get(key),
            vector_rank=vector_ranks.get(key),
            rrf_score=fused_scores[key],
        )
        for key in ordered[:limit]
    ]


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wnav_001(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    query: str,
    wiki_version_id: str | None = None,
    limit: int = DEFAULT_NAVIGATION_CANDIDATE_LIMIT,
    query_embedding: Sequence[float] | None = None,
    embedding_model: str = DEFAULT_WIKI_EMBEDDING_MODEL,
) -> list[WikiNavigationCandidate]:
    """[WNAV-001] Logical Index에서 관련 Wiki Page 후보를 조회한다.

    호출자가 전달한 Connection에서 RLS Scope를 설정하고 제목·별칭·Keyword와
    선택적 Vector 순위를 결합한다. 초기 절단에는 Graph degree를 사용하지 않는다.
    """
    if not user_id.strip():
        raise ValueError("WNAV-001에 user_id가 필요합니다.")
    if not query.strip():
        raise ValueError("WNAV-001에 query가 필요합니다.")
    if not 1 <= limit <= MAX_NAVIGATION_CANDIDATE_LIMIT:
        raise ValueError("WNAV-001 후보 수는 1에서 30 사이여야 합니다.")
    normalized_query = query.strip()
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        keyword_rows = await load_wiki_navigation_keyword_candidates(
            connection,
            user_id=user_id,
            query=normalized_query,
            wiki_version_id=wiki_version_id,
            limit=limit,
        )
        vector_rows: list[Mapping[str, object]] = []
        if query_embedding is not None:
            try:
                async with connection.transaction():
                    vector_rows = await load_wiki_navigation_vector_candidates(
                        connection,
                        user_id=user_id,
                        query_embedding=query_embedding,
                        wiki_version_id=wiki_version_id,
                        model_name=embedding_model,
                        limit=limit,
                    )
            except Exception as error:  # noqa: BLE001 - Keyword 폴백 경계
                logger.warning(
                    "Navigator Vector Locate 실패, Keyword 후보로 폴백합니다: %s",
                    error,
                )
    return _merge_candidate_rankings(keyword_rows, vector_rows, limit=limit)
