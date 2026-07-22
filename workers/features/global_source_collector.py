"""PostgreSQL Global Source Collector Worker.

GDELT·Naver 최신 뉴스 API를 키워드로 검색해 뉴스 기사 URL을 Global
Namespace에 중복 없이 저장한다. 본문은 저장하지 않고 `content_status='pending'`
상태로만 등록하며, 이후 Jina Reader Worker(global_content_fetcher)가 본문을
채운다. Provider별 실패는 서로 격리해 한 Provider가 실패해도 나머지 수집을
계속한다.
"""

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from infrastructure.persistence.api import (
    persist_collected_articles,
    set_system_job_scope,
)
from infrastructure.sources.connectors.api import (
    GdeltNewsProvider,
    LatestInformationProvider,
    LatestProviderError,
    NaverNewsProvider,
    col_002,
    col_003,
)
from infrastructure.sources.processing.api import gsp_004, gsp_006, gsp_015

type DictRow = dict[str, Any]

# 이 Worker가 지원하는 최신 뉴스 Provider 이름.
_SUPPORTED_PROVIDERS = ("gdelt", "naver")


def _build_provider(
    name: str,
    *,
    naver_client_id: str | None,
    naver_client_secret: str | None,
    gdelt_base_url: str | None,
) -> LatestInformationProvider:
    """이름과 자격 증명으로 최신 뉴스 Provider를 구성한다.

    Args:
        name: Provider 이름 (gdelt 또는 naver)
        naver_client_id: Naver 검색 API Client ID
        naver_client_secret: Naver 검색 API Client Secret
        gdelt_base_url: GDELT API 기본 URL (없으면 기본값 사용)

    Returns:
        키워드 검색이 가능한 Provider 인스턴스

    Raises:
        LatestProviderError: 지원하지 않는 Provider이거나 자격 증명이 없을 때
    """
    if name == "naver":
        if not naver_client_id or not naver_client_secret:
            raise LatestProviderError(
                name,
                "provider_not_ready",
                "NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET이 필요합니다.",
            )
        return NaverNewsProvider(naver_client_id, naver_client_secret)
    if name == "gdelt":
        return GdeltNewsProvider(gdelt_base_url or "https://api.gdeltproject.org")
    raise LatestProviderError(name, "unsupported_provider", "지원하지 않는 Provider입니다.")


async def run_global_source_collection_batch(
    *,
    database_url: str,
    keywords: list[str],
    providers: list[str] | None = None,
    limit_per_provider: int = 10,
    language: str | None = None,
    naver_client_id: str | None = None,
    naver_client_secret: str | None = None,
    gdelt_base_url: str | None = None,
) -> list[dict[str, object]]:
    """키워드로 GDELT·Naver 뉴스를 수집해 Global Namespace에 저장한다.

    Provider별로 독립적인 Transaction과 오류 처리를 사용해, 한 Provider의 API
    실패나 저장 오류가 다른 Provider의 수집 결과를 되돌리지 않는다.

    Args:
        database_url: Agent DB 연결 문자열
        keywords: 검색에 사용할 키워드 목록 (공백으로 합쳐 Query 구성)
        providers: 수집할 Provider 목록 (기본 gdelt, naver)
        limit_per_provider: Provider당 최대 수집 기사 수
        language: 검색 언어 힌트 (예: ko)
        naver_client_id: Naver 검색 API Client ID
        naver_client_secret: Naver 검색 API Client Secret
        gdelt_base_url: GDELT API 기본 URL

    Returns:
        Provider별 수집·저장 결과 또는 실패 정보 목록
    """
    query = " ".join(keyword.strip() for keyword in keywords if keyword.strip())
    if not query:
        raise ValueError("수집에 사용할 키워드가 필요합니다.")
    selected = providers or list(_SUPPORTED_PROVIDERS)
    connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
        database_url,
        row_factory=dict_row,
    )
    try:
        results: list[dict[str, object]] = []
        for provider_name in selected:
            try:
                provider = _build_provider(
                    provider_name,
                    naver_client_id=naver_client_id,
                    naver_client_secret=naver_client_secret,
                    gdelt_base_url=gdelt_base_url,
                )
                connector = col_002 if provider_name == "naver" else col_003
                collected = await connector(
                    provider,
                    query=query,
                    limit=limit_per_provider,
                    language=language,
                )
                normalized = await gsp_004(collected)
                articles = await gsp_006(normalized)
                await gsp_015("global")

                async def persist_articles() -> dict[str, int]:
                    """정규화된 기사를 Global Namespace에 멱등 저장한다."""
                    async with connection.transaction():
                        await set_system_job_scope(connection)
                        return await persist_collected_articles(
                            connection,
                            provider=provider_name,
                            query=query,
                            articles=articles,
                        )

                saved = await persist_articles()
            except LatestProviderError as error:
                results.append(
                    {
                        "provider": provider_name,
                        "status": "failed",
                        "error_code": error.error_code,
                        "error_message": str(error),
                    }
                )
            else:
                results.append(
                    {
                        "provider": provider_name,
                        "status": "completed",
                        "query": query,
                        **saved,
                    }
                )
        return results
    finally:
        await connection.close()


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def worker_001(
    *,
    database_url: str,
    keywords: list[str],
    providers: list[str] | None = None,
    limit_per_provider: int = 10,
    language: str | None = None,
    naver_client_id: str | None = None,
    naver_client_secret: str | None = None,
    gdelt_base_url: str | None = None,
) -> list[dict[str, object]]:
    """[WORKER-001] Global Source Collector Worker.

    외부 뉴스 데이터를 키워드로 수집하고 Global Source Pool에 저장한다. 실제
    수집·저장은 run_global_source_collection_batch에 위임하고, Provider별 결과
    목록을 반환한다.
    """
    if not database_url:
        raise ValueError("WORKER-001에 database_url이 필요합니다.")
    if not all(isinstance(keyword, str) for keyword in keywords):
        raise ValueError("WORKER-001의 keywords는 문자열 목록이어야 합니다.")
    if providers is not None and not all(isinstance(name, str) for name in providers):
        raise ValueError("WORKER-001의 providers는 문자열 목록이어야 합니다.")
    return await run_global_source_collection_batch(
        database_url=database_url,
        keywords=keywords,
        providers=providers,
        limit_per_provider=limit_per_provider,
        language=language,
        naver_client_id=naver_client_id,
        naver_client_secret=naver_client_secret,
        gdelt_base_url=gdelt_base_url,
    )
