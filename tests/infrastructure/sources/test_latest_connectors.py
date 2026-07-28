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
    # 디코더는 주입한다 — 단위 테스트가 Google 내부 엔드포인트를 호출하면 안 된다.
    provider = GoogleNewsRssProvider(
        transport=_rss_transport(xml),
        url_decoder=lambda url: "https://maeil.com/article/1",
    )

    articles = asyncio.run(provider.search(query="코스피", limit=10, language="ko"))

    assert len(articles) == 1  # link 없는 항목은 제외
    article = articles[0]
    assert article.provider == "google_news"
    assert article.title == "코스피 급락 - 매일경제"
    # 저장되는 URL은 리다이렉트가 아니라 디코딩된 원본 기사 주소다.
    assert article.url == "https://maeil.com/article/1"
    assert article.description == "코스피 급락"
    assert article.source_name == "매일경제"
    assert article.source_url == "https://maeil.com/article/1"
    assert article.published_at is not None
    assert article.language == "ko"


def test_google_news_rss_provider_drops_undecodable_items() -> None:
    """디코딩에 실패한 기사는 수집에서 제외한다.

    리다이렉트 URL을 그대로 저장하면 Jina Reader가 403을 반환해 본문을 확보할 수
    없고(2026-07-28 실측 111건 전원 실패), 풀에 제목만 남아 검색 점수만 높은
    잡음이 된다. 실패는 조용히 버리는 편이 낫다.
    """
    xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>디코딩 성공</title>
        <link>https://news.google.com/rss/articles/ok</link>
        <source url="https://maeil.com">매일경제</source>
      </item>
      <item>
        <title>디코딩 실패</title>
        <link>https://news.google.com/rss/articles/bad</link>
        <source url="https://maeil.com">매일경제</source>
      </item>
    </channel></rss>"""

    def decoder(url: str) -> str:
        """'ok'가 든 URL만 성공으로 취급한다."""
        return "https://maeil.com/article/1" if url.endswith("ok") else ""

    provider = GoogleNewsRssProvider(
        transport=_rss_transport(xml), url_decoder=decoder
    )

    articles = asyncio.run(provider.search(query="코스피", limit=10, language="ko"))

    assert [article.title for article in articles] == ["디코딩 성공"]


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


def test_naver_provider_queries_both_sorts_and_dedupes() -> None:
    """Naver는 최신순·관련도순을 모두 조회하고 URL로 중복을 제거한다.

    정렬 하나만 쓰면 신선도와 관련도 중 하나를 잃는다(2026-07-28 실측:
    'Cloudflare'가 sort=date에서 관련 3/10, sort=sim에서 관련 9/10이지만
    평균 190일 전 기사). 두 축을 모두 확보해 선별 계층이 판단하게 한다.
    """
    requested_sorts: list[str] = []
    shared = {
        "title": "공통 기사",
        "originallink": "https://example.com/shared",
        "description": "양쪽 정렬에 모두 등장",
        "pubDate": "Thu, 16 Jul 2026 09:00:00 +0900",
    }
    per_sort = {
        "date": {"items": [shared, {**shared, "originallink": "https://example.com/fresh"}]},
        "sim": {"items": [shared, {**shared, "originallink": "https://example.com/relevant"}]},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        """요청된 sort를 기록하고 정렬별로 다른 응답을 돌려준다."""
        sort = request.url.params.get("sort", "")
        requested_sorts.append(sort)
        payload = per_sort.get(sort, {"items": []})
        return httpx.Response(200, content=json.dumps(payload).encode(), request=request)

    provider = NaverNewsProvider("client", "secret", transport=httpx.MockTransport(handler))

    articles = asyncio.run(provider.search(query="Cloudflare", limit=10, language="ko"))

    assert sorted(requested_sorts) == ["date", "sim"]
    urls = [article.url for article in articles]
    # 양쪽에 걸친 기사는 한 번만 남고, 각 정렬 고유 기사는 모두 살아남는다.
    assert urls.count("https://example.com/shared") == 1
    assert "https://example.com/fresh" in urls
    assert "https://example.com/relevant" in urls


def test_naver_provider_propagates_failure() -> None:
    """정렬 조회 중 하나라도 실패하면 Provider 오류로 올린다.

    부분 결과를 조용히 반환하면 수집량이 왜 줄었는지 추적할 수 없다.
    """
    import pytest

    from infrastructure.sources.connectors.api import LatestProviderError

    def handler(request: httpx.Request) -> httpx.Response:
        """항상 5xx를 반환해 실패 경로를 재현한다."""
        return httpx.Response(500, request=request)

    provider = NaverNewsProvider("client", "secret", transport=httpx.MockTransport(handler))

    with pytest.raises(LatestProviderError):
        asyncio.run(provider.search(query="AI", limit=5, language="ko"))
