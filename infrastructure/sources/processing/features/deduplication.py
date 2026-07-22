"""Global Source 기사 URL 중복 제거 기능 구현."""

from collections.abc import Sequence

from infrastructure.sources.connectors.api import LatestArticle


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def gsp_006(articles: Sequence[LatestArticle]) -> list[LatestArticle]:
    """[GSP-006] 문서 중복 제거.

    동일 URL과 유사 문서를 중복 제거한다.
    """
    unique: list[LatestArticle] = []
    seen_urls: set[str] = set()
    for article in articles:
        key = article.url.strip().casefold()
        if not key or key in seen_urls:
            continue
        seen_urls.add(key)
        unique.append(article)
    return unique
