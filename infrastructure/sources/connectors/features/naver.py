"""Naver 최신 정보 수집 기능 구현."""

from infrastructure.sources.connectors.features.latest import (
    LatestArticle,
    LatestInformationProvider,
    LatestProviderError,
)


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def col_002(
    provider: LatestInformationProvider,
    *,
    query: str,
    limit: int,
    language: str | None = None,
) -> list[LatestArticle]:
    """[COL-002] Naver API 수집.

    설정된 키워드로 Naver API 데이터를 수집한다.
    """
    if provider.name != "naver":
        raise LatestProviderError(
            provider.name, "provider_mismatch", "COL-002에는 Naver Provider가 필요합니다."
        )
    return await provider.search(query=query, limit=limit, language=language)
