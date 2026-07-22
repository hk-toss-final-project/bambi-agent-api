"""개인 Wiki와 Global 문서 Hybrid Search 기능 구현."""

from typing import Any

from psycopg import AsyncConnection

from infrastructure.persistence.features.generation_runtime import load_report_context
from shared.report_models import ReportContextDocument


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def prag_003(
    connection: AsyncConnection[dict[str, Any]],
    *,
    user_id: str,
    query: str,
    top_k_per_scope: int = 5,
) -> list[ReportContextDocument]:
    """[PRAG-003] Hybrid Search.

    Keyword와 Vector 검색 결과를 결합한다.
    """
    if not user_id:
        raise ValueError("PRAG-003에 user_id가 필요합니다.")
    if not query.strip():
        raise ValueError("PRAG-003에 검색어가 필요합니다.")
    return await load_report_context(
        connection,
        user_id=user_id,
        query=query,
        top_k_per_scope=top_k_per_scope,
    )
