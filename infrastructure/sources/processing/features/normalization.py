"""Global Source 기사 정규화 기능과 언어 감지 Scaffold."""

from collections.abc import Sequence
from dataclasses import replace

from infrastructure.sources.connectors.api import LatestArticle
from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def gsp_004(articles: Sequence[LatestArticle]) -> list[LatestArticle]:
    """[GSP-004] API 응답 정규화.

    Source별 응답을 공통 문서 구조로 변환한다.
    """
    normalized: list[LatestArticle] = []
    for article in articles:
        url = article.url.strip()
        if not url:
            continue
        normalized.append(
            replace(
                article,
                provider=article.provider.strip(),
                title=article.title.strip(),
                url=url,
                description=article.description.strip(),
                source_name=(article.source_name or "").strip() or None,
                language=(article.language or "").strip() or None,
            )
        )
    return normalized


async def gsp_005(request: FeatureRequest) -> FeatureResult:
    """[GSP-005] 문서 언어 감지.

    수집된 문서의 언어를 판별한다.
    """
    raise NotImplementedError("[GSP-005] 기능 구현이 필요합니다.")
