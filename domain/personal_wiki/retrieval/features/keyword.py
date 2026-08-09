"""개인 Wiki와 Global 저장 자료의 Keyword·Trigram 검색 기능."""

from typing import Any

from psycopg import AsyncConnection

from infrastructure.persistence.api import load_report_context
from shared.report_models import ReportContextDocument


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def prag_001(
    connection: AsyncConnection[dict[str, Any]],
    *,
    user_id: str,
    query: str,
    top_k_per_scope: int = 5,
) -> list[ReportContextDocument]:
    """[PRAG-001] Keyword Search.

    개인 Wiki와 Global 저장 자료에서 FTS·Trigram 기반 후보를 조회한다.
    """
    if not user_id.strip():
        raise ValueError("PRAG-001에 user_id가 필요합니다.")
    if not query.strip():
        raise ValueError("PRAG-001에 검색어가 필요합니다.")
    return await load_report_context(
        connection,
        user_id=user_id,
        query=query,
        top_k_per_scope=top_k_per_scope,
    )
