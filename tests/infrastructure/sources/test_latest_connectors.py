"""Naver·NewsAPI·GDELT 최신 정보 Connector 정규화를 검증한다."""

import asyncio
import json

import httpx

from infrastructure.sources.connectors.api import (
    GdeltNewsProvider,
    GoogleNewsRssProvider,
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


def _rss_transport(xml: str) -> httpx.MockTransport:
    """RSS XML 텍스트를 반환하는 테스트 Transport를 만든다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=xml)

    return httpx.MockTransport(handler)


def test_google_news_rss_provider_normalizes_items() -> None:
    """Google News RSS 항목을 매체명·게시일 포함 공통 기사 모델로 변환한다."""
    xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>코스피 급락 - 매일경제</title>
        <link>https://news.google.com/rss/articles/abc</link>
        <pubDate>Thu, 23 Jul 2026 09:00:00 GMT</pubDate>
        <description>&lt;a href="x"&gt;코스피 급락&lt;/a&gt;</description>
        <source url="https://maeil.com">매일경제</source>
      </item>
      <item>
        <title>링크 없는 항목</title>
        <link></link>
      </item>
    </channel></rss>"""
    provider = GoogleNewsRssProvider(transport=_rss_transport(xml))

    articles = asyncio.run(provider.search(query="코스피", limit=10, language="ko"))

    assert len(articles) == 1  # link 없는 항목은 제외
    article = articles[0]
    assert article.provider == "google_news"
    assert article.title == "코스피 급락 - 매일경제"
    assert article.url == "https://news.google.com/rss/articles/abc"
    assert article.description == "코스피 급락"
    assert article.source_name == "매일경제"
    assert article.published_at is not None
    assert article.language == "ko"


def test_google_news_rss_provider_applies_limit_and_rejects_bad_feed() -> None:
    """limit을 초과한 항목은 잘리고, XML이 아니면 invalid_feed 오류를 낸다."""
    items = "".join(
        f"<item><title>기사{i}</title><link>https://n.example/{i}</link></item>"
        for i in range(5)
    )
    provider = GoogleNewsRssProvider(
        transport=_rss_transport(f"<rss><channel>{items}</channel></rss>")
    )
    articles = asyncio.run(provider.search(query="AI", limit=3, language="ko"))
    assert [a.url for a in articles] == [
        "https://n.example/0", "https://n.example/1", "https://n.example/2"
    ]

    broken = GoogleNewsRssProvider(transport=_rss_transport("html 오류 페이지"))
    try:
        asyncio.run(broken.search(query="AI", limit=3, language="ko"))
    except Exception as error:
        assert getattr(error, "error_code", "") == "invalid_feed"
    else:
        raise AssertionError("invalid_feed 오류가 발생해야 합니다.")


def test_col_001_requires_google_news_provider() -> None:
    """COL-001은 Google News RSS Provider만 허용한다."""
    from infrastructure.sources.connectors.api import col_001

    class _WrongProvider:
        name = "naver"

        async def search(self, *, query, limit, language):
            return []

    try:
        asyncio.run(col_001(_WrongProvider(), query="AI", limit=3))
    except Exception as error:
        assert getattr(error, "error_code", "") == "provider_mismatch"
    else:
        raise AssertionError("provider_mismatch 오류가 발생해야 합니다.")
