"""개인 Wiki와 Global 문서 Hybrid Search 기능 구현."""

import logging
from collections.abc import Sequence
from typing import Any

from psycopg import AsyncConnection

from shared.report_models import ReportContextDocument

from .keyword import prag_001
from .reranking import prag_004
from .vector import DEFAULT_WIKI_EMBEDDING_MODEL, prag_002

logger = logging.getLogger("domain.personal_wiki.retrieval.hybrid")


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def prag_003(
    connection: AsyncConnection[dict[str, Any]],
    *,
    user_id: str,
    query: str,
    top_k_per_scope: int = 5,
    query_embedding: Sequence[float] | None = None,
    embedding_model: str = DEFAULT_WIKI_EMBEDDING_MODEL,
) -> list[ReportContextDocument]:
    """[PRAG-003] Hybrid Search.

    Keyword와 Vector 검색 결과를 결합한다.
    """
    if not user_id:
        raise ValueError("PRAG-003에 user_id가 필요합니다.")
    if not query.strip():
        raise ValueError("PRAG-003에 검색어가 필요합니다.")
    keyword = await prag_001(
        connection,
        user_id=user_id,
        query=query,
        top_k_per_scope=top_k_per_scope,
    )
    personal_keyword = [
        document for document in keyword if document.namespace_key != "global"
    ]
    global_keyword = [
        document for document in keyword if document.namespace_key == "global"
    ]
    vector: list[ReportContextDocument] = []
    if query_embedding is not None:
        try:
            vector = await prag_002(
                connection,
                user_id=user_id,
                query_embedding=query_embedding,
                top_k=top_k_per_scope,
                model_name=embedding_model,
            )
        except Exception as error:  # noqa: BLE001 - Vector 장애는 Keyword로 격리한다.
            logger.warning(
                "개인 Wiki Vector 검색 실패, Keyword 결과로 폴백합니다: %s", error
            )
    personal = await prag_004(
        personal_keyword,
        vector,
        top_k=top_k_per_scope,
    )
    return [*personal, *global_keyword[:top_k_per_scope]]
