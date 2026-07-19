"""Naver·NewsAPI·GDELT 최신 정보 Connector 정규화를 검증한다."""

import asyncio
import json

import httpx

from infrastructure.sources.connectors.api import (
    GdeltNewsProvider,
    NaverNewsProvider,
    NewsApiProvider,
)


def _transport(payload: dict[str, object]) -> httpx.MockTransport:
    """지정된 JSON을 반환하는 HTTP Mock Transport를 만든다."""

    def handler(request: httpx.Request) -> httpx.Response:
        """외부 요청에 결정적인 JSON 응답을 반환한다."""
        return httpx.Response(200, content=json.dumps(payload).encode(), request=request)

    return httpx.MockTransport(handler)


def test_naver_provider_removes_html_and_parses_rfc_date() -> None:
    """Naver 검색 결과의 HTML과 RFC 게시일을 공통 기사 모델로 변환한다."""
    provider = NaverNewsProvider(
        "client",
        "secret",
        transport=_transport(
            {
                "items": [
                    {
                        "title": "<b>AI</b> 뉴스",
                        "originallink": "https://example.com/naver",
                        "description": "&quot;에이전트&quot; 소식",
                        "pubDate": "Thu, 16 Jul 2026 09:00:00 +0900",
                    }
                ]
            }
        ),
    )

    articles = asyncio.run(provider.search(query="AI", limit=10, language="ko"))

    assert articles[0].title == "AI 뉴스"
    assert articles[0].description == '"에이전트" 소식'
    assert articles[0].published_at is not None


def test_newsapi_and_gdelt_providers_normalize_articles() -> None:
    """NewsAPI와 GDELT 응답이 동일한 LatestArticle 필드를 채우는지 검증한다."""
    newsapi = NewsApiProvider(
        "key",
        transport=_transport(
            {
                "articles": [
                    {
                        "title": "Agent update",
                        "url": "https://example.com/newsapi",
                        "description": "New release",
                        "publishedAt": "2026-07-16T00:00:00Z",
                        "source": {"name": "Example"},
                    }
                ]
            }
        ),
    )
    gdelt = GdeltNewsProvider(
        transport=_transport(
            {
                "articles": [
                    {
                        "title": "Global agent news",
                        "url": "https://example.com/gdelt",
                        "seendate": "20260716T010203Z",
                        "domain": "example.com",
                        "language": "English",
                    }
                ]
            }
        )
    )

    newsapi_items = asyncio.run(
        newsapi.search(query="agent", limit=5, language="en")
    )
    gdelt_items = asyncio.run(gdelt.search(query="agent", limit=5, language="en"))

    assert newsapi_items[0].source_name == "Example"
    assert newsapi_items[0].provider == "newsapi"
    assert gdelt_items[0].provider == "gdelt"
    assert gdelt_items[0].published_at is not None
