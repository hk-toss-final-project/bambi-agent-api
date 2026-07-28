"""PostgreSQL Global 뉴스 본문 수집 Worker (Jina Reader).

Global Source Collector가 수집 캐시(`global_source_documents`)에 저장한 뉴스
기사 URL 중 아직 본문이 없는(`content_status='pending'`) 문서를 점유해,
Jina Reader(r.jina.ai)로 원문 본문을 정제해 가져온 뒤 캐시 문서에 채운다.
문서별로 독립적인 Transaction과 오류 처리를 사용해 한 URL의 실패가 다른
URL의 저장을 되돌리지 않는다.
"""

from asyncio import to_thread
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from infrastructure.persistence.api import (
    GlobalArticleToFetch,
    claim_global_articles_for_fetch,
    mark_global_article_fetch_failed,
    save_fetched_article_content,
    set_system_job_scope,
)
from infrastructure.sources.connectors.api import (
    JinaReadError,
    JinaReadResult,
    fetch_url_via_jina,
)

type DictRow = dict[str, Any]
type UrlFetcher = Callable[[str], JinaReadResult]


def _parse_published_at(value: str | None) -> datetime | None:
    """Jina Reader의 게시 시각 문자열을 timezone 포함 datetime으로 변환한다."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def _fetch_one(
    connection: AsyncConnection[DictRow],
    *,
    article: GlobalArticleToFetch,
    url_fetcher: UrlFetcher,
) -> dict[str, object]:
    """점유한 기사 하나의 본문을 수집해 저장하거나 실패로 표시한다."""
    try:
        fetched = await to_thread(url_fetcher, article.url)
    except JinaReadError as error:
        async with connection.transaction():
            await set_system_job_scope(connection)
            await mark_global_article_fetch_failed(
                connection,
                document_id=article.document_id,
                error_code=f"JINA_{error.error_code.upper()}",
                error_message=str(error),
            )
        return {
            "document_id": article.document_id,
            "url": article.url,
            "status": "failed",
            "error_code": f"JINA_{error.error_code.upper()}",
        }
    async with connection.transaction():
        await set_system_job_scope(connection)
        saved = await save_fetched_article_content(
            connection,
            document_id=article.document_id,
            resolved_url=fetched.resolved_url,
            title=fetched.title,
            markdown=fetched.markdown,
            published_at=_parse_published_at(fetched.published_time),
        )
    return {"url": article.url, "status": "completed", **saved}


async def run_global_content_fetch_batch(
    *,
    database_url: str,
    limit: int = 5,
    url_fetcher: UrlFetcher = fetch_url_via_jina,
) -> list[dict[str, object]]:
    """본문이 없는 Global 기사 Batch를 점유해 Jina Reader로 본문을 채운다.

    Args:
        database_url: Agent DB 연결 문자열
        limit: 한 번에 처리할 최대 문서 수
        url_fetcher: URL 본문 수집기 (테스트에서 네트워크 대체용)

    Returns:
        문서별 본문 수집 결과 또는 실패 정보 목록
    """
    connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
    )
    try:
        async with connection.transaction():
            await set_system_job_scope(connection)
            articles = await claim_global_articles_for_fetch(connection, limit=limit)
        results: list[dict[str, object]] = []
        for article in articles:
            results.append(
                await _fetch_one(
                    connection,
                    article=article,
                    url_fetcher=url_fetcher,
                )
            )
        return results
    finally:
        await connection.close()
