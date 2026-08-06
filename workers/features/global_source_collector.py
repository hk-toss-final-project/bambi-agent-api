"""PostgreSQL Global Source Collector Worker.

GDELT·Naver·Google News RSS·NewsAPI·YouTube·Reddit을 키워드로 검색해 문서 URL을
Global 수집 캐시에 중복 없이 저장한다. 본문은 저장하지 않고
`content_status='pending'` 상태로만 등록하며, 이후 Jina Reader
Worker(global_content_fetcher)가 본문을 채운다. Provider별 실패는 서로 격리해
한 Provider가 실패해도 나머지 수집을 계속한다.

NewsAPI는 자격 증명과 무료 플랜 호출 한도(일 100회)가 있어 기본 Provider
목록에서는 제외한다. 호출자가 명시적으로 지정할 때만 수집한다.

YouTube·Reddit(COL-005)은 자격 증명이 없어도 동작하지만 기본 목록에서는
제외한다. 뉴스와 성격이 다른 소스라 필요할 때만 골라 쓰는 편이 낫고, Reddit은
비인증 요청 레이트리밋이 빡빡해 매 tick 호출할 대상이 아니기 때문이다.

SNS 두 Provider는 검색 범위·정렬을 `search_options`로 조정한다. 기본값은
"최근에 주목받은 글"을 향하고(_SNS_SEARCH_DEFAULTS), Source별로 다르게 하려면
`global_sources.connector_config.search_options`에 넣어 덮어쓴다.
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
    GoogleNewsRssProvider,
    LatestInformationProvider,
    LatestProviderError,
    NaverNewsProvider,
    NewsApiProvider,
    RedditSearchProvider,
    YouTubeSearchProvider,
    col_001,
    col_002,
    col_003,
    col_004,
    col_005,
)
from infrastructure.sources.processing.api import gsp_004, gsp_006, gsp_015

type DictRow = dict[str, Any]

# 이 Worker가 지원하는 Provider 이름.
_SUPPORTED_PROVIDERS = (
    "gdelt",
    "naver",
    "google_news",
    "newsapi",
    "youtube",
    "reddit",
)

# 호출자가 Provider를 지정하지 않았을 때 수집할 기본 Provider 이름.
# NewsAPI는 무료 플랜 호출 한도가 낮아, YouTube·Reddit은 뉴스와 성격이 다른
# 소스라 기본값에서 제외한다.
_DEFAULT_PROVIDERS = ("gdelt", "naver", "google_news")

# SNS Provider의 기본 검색 조건. "최신순으로 아무거나"가 아니라 "최근에 주목받은
# 글"을 받도록 맞춘 값이다.
#
# - youtube: 관련도순 기본 검색은 조회수 200회짜리 개인 채널과 10개월 전 영상을
#   함께 돌려준다(2026-07-29 실측). 최근 1주로 좁히고 조회수순으로 받으면 같은
#   키워드에서 주요 언론·대형 채널의 최신 영상이 상위에 온다.
# - reddit: 전체 검색 최신순은 주제와 무관한 개인 글을 그대로 담는다. 점수순으로
#   받아 커뮤니티가 이미 걸러 준 결과를 쓴다. 서브레딧 화이트리스트는 주제마다
#   달라 기본값을 두지 않고 Source 설정에 맡긴다.
#
# 개념·튜토리얼 키워드를 수집하는 Source는 최근 1주로 좁히면 안 되므로
# connector_config에서 upload_window를 빼거나 넓혀서 덮어쓴다.
_SNS_SEARCH_DEFAULTS: dict[str, dict[str, object]] = {
    "youtube": {"upload_window": "thisWeek", "sort_by": "viewCount"},
    "reddit": {"sort": "top", "time_filter": "week"},
}

# Provider별 수집 기능(COL-*) 매핑. SNS 두 곳은 COL-005가 함께 담당한다.
_PROVIDER_CONNECTORS = {
    "naver": col_002,
    "gdelt": col_003,
    "google_news": col_001,
    "newsapi": col_004,
    "youtube": col_005,
    "reddit": col_005,
}


def _sns_search_options(
    name: str, search_options: dict[str, object] | None
) -> dict[str, object]:
    """SNS Provider의 기본 검색 조건에 Source별 설정을 덮어쓴다."""
    merged = dict(_SNS_SEARCH_DEFAULTS.get(name, {}))
    merged.update(search_options or {})
    return merged


def _build_provider(
    name: str,
    *,
    naver_client_id: str | None,
    naver_client_secret: str | None,
    gdelt_base_url: str | None,
    news_api_key: str | None = None,
    search_options: dict[str, object] | None = None,
) -> LatestInformationProvider:
    """이름과 자격 증명으로 수집 Provider를 구성한다.

    Args:
        name: Provider 이름 (gdelt, naver, google_news, newsapi, youtube, reddit)
        naver_client_id: Naver 검색 API Client ID
        naver_client_secret: Naver 검색 API Client Secret
        gdelt_base_url: GDELT API 기본 URL (없으면 기본값 사용)
        news_api_key: NewsAPI Key (newsapi Provider에만 필요)
        search_options: SNS Provider의 검색 범위·정렬 설정. 기본값을 덮어쓴다.

    Returns:
        키워드 검색이 가능한 Provider 인스턴스

    Raises:
        LatestProviderError: 지원하지 않는 Provider이거나 자격 증명이 없을 때,
            또는 SNS 검색 설정 값이 잘못됐을 때
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
    if name == "google_news":
        return GoogleNewsRssProvider()
    if name == "newsapi":
        if not news_api_key:
            raise LatestProviderError(
                name,
                "provider_not_ready",
                "NEWS_API_KEY가 필요합니다.",
            )
        return NewsApiProvider(news_api_key)
    # YouTube·Reddit은 자격 증명 없이 공개 검색으로 동작한다. 검색 조건이 잘못된
    # 경우 Provider가 ValueError를 던지므로, Provider 실패로 감싸 다른 Provider의
    # 수집을 막지 않는다.
    if name in ("youtube", "reddit"):
        options = _sns_search_options(name, search_options)
        try:
            if name == "youtube":
                return YouTubeSearchProvider(**options)  # type: ignore[arg-type]
            return RedditSearchProvider(**options)  # type: ignore[arg-type]
        except (TypeError, ValueError) as error:
            raise LatestProviderError(
                name,
                "invalid_search_options",
                f"검색 설정이 잘못됐습니다: {error}",
            ) from error
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
    news_api_key: str | None = None,
    search_options: dict[str, object] | None = None,
    source_key: str | None = None,
    target_key: str | None = None,
) -> list[dict[str, object]]:
    """키워드로 뉴스·SNS Provider를 검색해 Global 수집 캐시에 저장한다.

    Provider별로 독립적인 Transaction과 오류 처리를 사용해, 한 Provider의 API
    실패나 저장 오류가 다른 Provider의 수집 결과를 되돌리지 않는다.

    Args:
        database_url: Agent DB 연결 문자열
        keywords: 검색에 사용할 키워드 목록 (공백으로 합쳐 Query 구성)
        providers: 수집할 Provider 목록 (기본 gdelt, naver, google_news)
        limit_per_provider: Provider당 최대 수집 기사 수
        language: 검색 언어 힌트 (예: ko)
        naver_client_id: Naver 검색 API Client ID
        naver_client_secret: Naver 검색 API Client Secret
        gdelt_base_url: GDELT API 기본 URL
        news_api_key: NewsAPI Key
        search_options: SNS Provider의 검색 범위·정렬 설정 (기본값을 덮어쓴다)
        source_key: 실행 이력을 귀속할 Source Key. 정기 수집은 실행을 지시한
            Source의 Key를 넘긴다. 생략하면 Provider 기본 Source에 기록한다
        target_key: 이 수집을 지시한 수집 대상(Topic)의 Key. 넘기면 검색어가
            Topic 이름과 달라도 그 Topic에 연결한다(확장 검색어용)

    Returns:
        Provider별 수집·저장 결과 또는 실패 정보 목록
    """
    query = " ".join(keyword.strip() for keyword in keywords if keyword.strip())
    if not query:
        raise ValueError("수집에 사용할 키워드가 필요합니다.")
    selected = providers or list(_DEFAULT_PROVIDERS)
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
                    news_api_key=news_api_key,
                    search_options=search_options,
                )
                connector = _PROVIDER_CONNECTORS[provider_name]
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
                    """정규화된 기사를 Global 수집 캐시에 멱등 저장한다."""
                    async with connection.transaction():
                        await set_system_job_scope(connection)
                        return await persist_collected_articles(
                            connection,
                            provider=provider_name,
                            query=query,
                            articles=articles,
                            source_key=source_key,
                            target_key=target_key,
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
    news_api_key: str | None = None,
    search_options: dict[str, object] | None = None,
    source_key: str | None = None,
    target_key: str | None = None,
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
    if search_options is not None and not isinstance(search_options, dict):
        raise ValueError("WORKER-001의 search_options는 딕셔너리여야 합니다.")
    return await run_global_source_collection_batch(
        database_url=database_url,
        keywords=keywords,
        providers=providers,
        limit_per_provider=limit_per_provider,
        language=language,
        naver_client_id=naver_client_id,
        naver_client_secret=naver_client_secret,
        gdelt_base_url=gdelt_base_url,
        news_api_key=news_api_key,
        search_options=search_options,
        source_key=source_key,
        target_key=target_key,
    )
