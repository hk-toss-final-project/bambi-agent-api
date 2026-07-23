"""Google News RSS 최신 정보 수집 기능 구현."""

from infrastructure.sources.connectors.features.latest import (
    LatestArticle,
    LatestInformationProvider,
    LatestProviderError,
)


# MVP: 뉴스 소스 커버리지 통합으로 구현 대상에 포함된 기능입니다.
async def col_001(
    provider: LatestInformationProvider,
    *,
    query: str,
    limit: int,
    language: str | None = None,
) -> list[LatestArticle]:
    """[COL-001] RSS 수집.

    등록된 RSS Feed(Google News 검색 피드)에서 신규 콘텐츠를 수집한다.
    """
    if provider.name != "google_news":
        raise LatestProviderError(
            provider.name,
            "provider_mismatch",
            "COL-001에는 Google News RSS Provider가 필요합니다.",
        )
    return await provider.search(query=query, limit=limit, language=language)
