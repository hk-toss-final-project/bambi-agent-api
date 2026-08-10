"""LLM Wiki Navigator 애플리케이션 서비스.

질문 임베딩은 DB Transaction 밖에서 계산하고 Repository에는 Navigator가
사용할 후보·읽기 예산만 전달한다.
"""

from __future__ import annotations

import logging
from asyncio import to_thread
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from agent.report_builder.api import embed_wiki_queries
from app.schemas.wiki_navigation import WikiNavigateRequest, WikiNavigateResponse
from shared.wiki_navigation_models import WikiNavigationPacket

logger = logging.getLogger("app.services.wiki_navigator")


class WikiNavigatorRepository(Protocol):
    """하나의 DB 연결에서 Wiki Navigation을 수행하는 Repository 계약."""

    async def navigate_wiki(
        self,
        user_id: str,
        *,
        query: str,
        selected_document_version_ids: Sequence[str],
        wiki_version_id: str | None,
        candidate_limit: int,
        max_depth: int,
        max_pages: int,
        max_chunks: int,
        query_embedding: Sequence[float] | None,
    ) -> WikiNavigationPacket:
        """Locate와 선택 Page 읽기를 같은 Connection에서 수행한다."""
        ...


class WikiNavigatorService:
    """WNAV-006 결과를 검증된 API Context Packet으로 변환한다."""

    def __init__(
        self,
        repository: WikiNavigatorRepository,
        *,
        embedding_function: Callable[[Sequence[str]], Mapping[str, list[float]]] = (
            embed_wiki_queries
        ),
    ) -> None:
        """Navigator Repository와 질문 임베딩 함수를 주입한다."""
        self._repository = repository
        self._embedding_function = embedding_function

    async def navigate(
        self, user_id: str, payload: WikiNavigateRequest
    ) -> WikiNavigateResponse:
        """질문 후보를 찾고 선택된 Page가 있으면 Context Packet까지 읽는다."""
        query = payload.query.strip()
        query_embedding: Sequence[float] | None = None
        try:
            embeddings = await to_thread(self._embedding_function, [query])
            query_embedding = embeddings.get(query)
        except Exception as error:  # noqa: BLE001 - Keyword Locate 폴백
            logger.warning("Navigator 질문 임베딩 실패, Keyword로 폴백합니다: %s", error)
        packet = await self._repository.navigate_wiki(
            user_id,
            query=query,
            selected_document_version_ids=payload.selected_document_version_ids,
            wiki_version_id=payload.wiki_version_id,
            candidate_limit=payload.candidate_limit,
            max_depth=payload.max_depth,
            max_pages=payload.max_pages,
            max_chunks=payload.max_chunks,
            query_embedding=query_embedding,
        )
        return WikiNavigateResponse.model_validate(packet)
