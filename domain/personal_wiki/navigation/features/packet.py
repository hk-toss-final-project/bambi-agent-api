"""Navigator Context Packet 조립과 상위 오케스트레이션 기능."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace
from hashlib import sha256
from typing import Any

from psycopg import AsyncConnection

from shared.wiki_navigation_models import (
    WikiNavigationCandidate,
    WikiNavigationPacket,
    WikiNavigationPage,
    WikiNavigationRelation,
    WikiNavigationSource,
    WikiNavigationTraceStep,
    WikiNavigationTraversal,
)
from shared.wiki_navigation_policy import (
    DEFAULT_WIKI_NAVIGATION_POLICY,
    WikiNavigationBudget,
)

from .read import wnav_002, wnav_004
from .traversal import wnav_003

logger = logging.getLogger("domain.personal_wiki.navigation.packet")

type DictRow = dict[str, Any]


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wnav_005(
    *,
    query: str,
    wiki_version_id: str | None,
    candidates: Sequence[WikiNavigationCandidate],
    pages: Sequence[WikiNavigationPage],
    relations: Sequence[WikiNavigationRelation],
    sources: Sequence[WikiNavigationSource],
    truncated: bool = False,
    fallback_reason: str | None = None,
    budget: WikiNavigationBudget = DEFAULT_WIKI_NAVIGATION_POLICY.budget,
) -> WikiNavigationPacket:
    """[WNAV-005] 읽은 Page·관계·Source를 답변 없는 Context Packet으로 조립한다."""
    if not query.strip():
        raise ValueError("WNAV-005에 query가 필요합니다.")
    trace = (
        WikiNavigationTraceStep(
            step="locate",
            document_ids=tuple(item.document_id for item in candidates),
            details=(("candidate_count", str(len(candidates))),),
        ),
        WikiNavigationTraceStep(
            step="read",
            document_ids=tuple(item.document_id for item in pages),
            details=(("page_count", str(len(pages))),),
        ),
        WikiNavigationTraceStep(
            step="traverse",
            document_ids=tuple(
                dict.fromkeys(
                    item.target_document_id
                    for item in relations
                    if item.target_document_id
                )
            ),
            details=(("relation_count", str(len(relations))),),
        ),
    )
    return WikiNavigationPacket(
        query=query.strip(),
        wiki_version_id=wiki_version_id,
        candidates=tuple(candidates),
        pages=tuple(pages),
        relations=tuple(relations),
        sources=tuple(sources),
        trace=trace,
        truncated=truncated,
        fallback_reason=fallback_reason,
        budget=budget,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wnav_006(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    query: str,
    selected_document_version_ids: Sequence[str],
    candidates: Sequence[WikiNavigationCandidate] = (),
    wiki_version_id: str | None = None,
    max_depth: int = 1,
    max_pages: int = 6,
    max_chunks: int = 12,
    max_seed_pages: int | None = None,
    hop_page_limits: Sequence[int] | None = None,
) -> WikiNavigationPacket:
    """[WNAV-006] Consumer가 선택한 Seed를 읽고 제한적으로 탐색한다."""
    budget = WikiNavigationBudget(
        max_depth=max_depth,
        max_seed_pages=max_seed_pages if max_seed_pages is not None else max_pages,
        max_pages=max_pages,
        max_chunks=max_chunks,
        hop_page_limits=(
            tuple(int(limit) for limit in hop_page_limits)
            if hop_page_limits is not None
            else tuple(max_pages for _ in range(max_depth))
        ),
    )
    if not selected_document_version_ids:
        return await wnav_005(
            query=query,
            wiki_version_id=wiki_version_id,
            candidates=candidates,
            pages=(),
            relations=(),
            sources=(),
            budget=budget,
        )
    selected_seed_versions = list(
        dict.fromkeys(
            str(version_id).strip()
            for version_id in selected_document_version_ids
            if str(version_id).strip()
        )
    )
    seed_truncated = len(selected_seed_versions) > budget.max_seed_pages
    selected_seed_versions = selected_seed_versions[: budget.max_seed_pages]
    seed_pages = await wnav_002(
        connection,
        user_id=user_id,
        document_version_ids=selected_seed_versions,
        wiki_version_id=wiki_version_id,
        max_chunks_per_page=max(1, max_chunks // max_pages),
    )
    seed_document_ids = [page.document_id for page in seed_pages]
    fallback_reason: str | None = None
    try:
        traversal = await wnav_003(
            connection,
            user_id=user_id,
            seed_document_ids=seed_document_ids,
            max_depth=max_depth,
            max_pages=max_pages,
            seed_page_limit=budget.max_seed_pages,
            hop_page_limits=budget.hop_page_limits,
        )
    except Exception as error:  # noqa: BLE001 - Page Read 보존 폴백
        logger.warning(
            "event=wiki_navigation_relation_traversal_failed "
            "user_id=%s query_hash=%s wiki_version_id=%s seed_page_count=%d "
            "max_depth=%d max_pages=%d error_type=%s error=%s",
            user_id,
            sha256(query.strip().encode("utf-8")).hexdigest()[:16],
            wiki_version_id or "-",
            len(seed_document_ids),
            max_depth,
            max_pages,
            type(error).__name__,
            error,
        )
        traversal = WikiNavigationTraversal(
            tuple(seed_document_ids),
            (),
            document_hops=tuple((item, 0) for item in seed_document_ids),
        )
        fallback_reason = "relation_traversal_failed"
    pages = await wnav_002(
        connection,
        user_id=user_id,
        document_version_ids=selected_seed_versions,
        document_ids=traversal.document_ids,
        wiki_version_id=wiki_version_id,
        max_chunks_per_page=max(1, max_chunks // max_pages),
    )
    hop_by_document = dict(traversal.document_hops)
    pages = [
        replace(page, hops=hop_by_document.get(page.document_id, 0))
        if isinstance(page, WikiNavigationPage)
        else page
        for page in pages
    ]
    sources = await wnav_004(
        connection,
        user_id=user_id,
        wiki_document_version_ids=[page.document_version_id for page in pages],
    )
    return await wnav_005(
        query=query,
        wiki_version_id=wiki_version_id,
        candidates=candidates,
        pages=pages,
        relations=traversal.relations,
        sources=sources,
        truncated=seed_truncated or traversal.truncated,
        fallback_reason=fallback_reason,
        budget=budget,
    )
