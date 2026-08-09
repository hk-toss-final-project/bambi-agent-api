"""기존 Wiki Embedding을 이용한 개인 Wiki 의미 검색 기능."""

from collections.abc import Sequence
from typing import Any

from psycopg import AsyncConnection

from infrastructure.persistence.api import load_personal_wiki_vector_context
from shared.report_models import ReportContextDocument

DEFAULT_WIKI_EMBEDDING_MODEL = "text-embedding-3-small"
WIKI_EMBEDDING_DIMENSIONS = 1536


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def prag_002(
    connection: AsyncConnection[dict[str, Any]],
    *,
    user_id: str,
    query_embedding: Sequence[float],
    top_k: int = 5,
    model_name: str = DEFAULT_WIKI_EMBEDDING_MODEL,
) -> list[ReportContextDocument]:
    """[PRAG-002] Vector Search.

    활성 Embedding 설정과 동일한 모델의 현재 개인 Wiki Chunk를 의미 검색한다.
    """
    if not user_id.strip():
        raise ValueError("PRAG-002에 user_id가 필요합니다.")
    if len(query_embedding) != WIKI_EMBEDDING_DIMENSIONS:
        raise ValueError(
            "PRAG-002 Query Embedding은 "
            f"{WIKI_EMBEDDING_DIMENSIONS}차원이어야 합니다."
        )
    if not model_name.strip():
        raise ValueError("PRAG-002에 Embedding 모델 이름이 필요합니다.")
    return await load_personal_wiki_vector_context(
        connection,
        user_id=user_id,
        query_embedding=query_embedding,
        model_name=model_name,
        top_k=top_k,
    )
