"""GDELT 최신 정보 수집 기능 구현."""

from infrastructure.sources.connectors.features.latest import (
    LatestArticle,
    LatestInformationProvider,
    LatestProviderError,
)


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def col_003(
    provider: LatestInformationProvider,
    *,
    query: str,
    limit: int,
    language: str | None = None,
) -> list[LatestArticle]:
    """[COL-003] GDELT 수집.

    글로벌 뉴스와 이벤트 데이터를 수집한다.
    """
    if provider.name != "gdelt":
        raise LatestProviderError(
            provider.name, "provider_mismatch", "COL-003에는 GDELT Provider가 필요합니다."
        )
    return await provider.search(query=query, limit=limit, language=language)
