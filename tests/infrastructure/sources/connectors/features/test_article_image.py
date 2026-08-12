"""원본 HTML 메타데이터 기반 기사 대표 이미지 추출을 검증한다."""

import httpx
import pytest

from infrastructure.sources.connectors.features.article_image import (
    ArticleImageFetchError,
    extract_article_image_metadata,
    fetch_article_image_metadata,
)


def test_open_graph_image_wins_over_ai_widget_and_body_image() -> None:
    """제목 뒤 AI 아이콘이 먼저 있어도 Open Graph 대표 이미지를 선택한다."""
    html = """
    <html><head>
      <meta property="og:image"
            content="https://cdn.example/photos/article-main.jpg">
      <meta property="og:image:width" content="1200">
      <meta property="og:image:height" content="800">
    </head><body>
      <h1>대한체육회, 아시안게임 응원 열기</h1>
      <a href="/ai"><img src="/images/aichat/global_ani.png"
           alt="애니메이션 이미지" width="64" height="64"></a>
      <article><img src="/photos/body.jpg" width="1000" height="700"></article>
    </body></html>
    """

    result = extract_article_image_metadata(
        html, page_url="https://news.example/article/1"
    )

    assert result is not None
    assert result.url == "https://cdn.example/photos/article-main.jpg"
    assert result.source == "open_graph"
    assert result.width == 1200
    assert result.height == 800


def test_twitter_image_resolves_relative_url_when_open_graph_is_missing() -> None:
    """Open Graph가 없으면 Twitter Card의 상대 이미지 URL을 해석한다."""
    html = '<meta name="twitter:image" content="/images/twitter-cover.webp">'

    result = extract_article_image_metadata(
        html, page_url="https://news.example/articles/1"
    )

    assert result is not None
    assert result.url == "https://news.example/images/twitter-cover.webp"
    assert result.source == "twitter_card"


def test_json_ld_news_article_image_supports_image_object() -> None:
    """Twitter Card도 없으면 JSON-LD NewsArticle의 ImageObject를 사용한다."""
    html = """
    <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "image": {
          "@type": "ImageObject",
          "url": "https://cdn.example/schema-cover.jpg",
          "width": 1280,
          "height": 720
        }
      }
    </script>
    """

    result = extract_article_image_metadata(
        html, page_url="https://news.example/articles/2"
    )

    assert result is not None
    assert result.url == "https://cdn.example/schema-cover.jpg"
    assert result.source == "schema_org"
    assert result.width == 1280
    assert result.height == 720


def test_article_fallback_skips_small_icon_and_uses_large_image() -> None:
    """메타데이터가 없으면 article 안의 작은 아이콘 대신 큰 이미지를 고른다."""
    html = """
    <article>
      <img src="/images/global_ani.png" alt="애니메이션 이미지"
           width="64" height="64">
      <p>기사 첫 문단입니다.</p>
      <img src="/images/body-main.jpg" alt="현장 사진"
           width="1200" height="800">
    </article>
    """

    result = extract_article_image_metadata(
        html, page_url="https://news.example/articles/3"
    )

    assert result is not None
    assert result.url == "https://news.example/images/body-main.jpg"
    assert result.source == "article_dom"


def test_article_fallback_does_not_treat_percentage_width_as_pixels() -> None:
    """width=100%인 본문 이미지는 100픽셀 아이콘으로 오인하지 않는다."""
    html = """
    <article>
      <img src="/images/responsive-main.jpg" alt="현장 사진"
           width="100%" height="auto">
    </article>
    """

    result = extract_article_image_metadata(
        html, page_url="https://news.example/articles/responsive"
    )

    assert result is not None
    assert result.url == "https://news.example/images/responsive-main.jpg"


def test_open_graph_skips_invalid_first_candidate() -> None:
    """여러 Open Graph 이미지 중 첫 UI 자산을 건너뛰고 다음 사진을 사용한다."""
    html = """
    <meta property="og:image" content="https://cdn.example/images/logo.png">
    <meta property="og:image" content="https://cdn.example/photos/article.jpg">
    """

    result = extract_article_image_metadata(
        html, page_url="https://news.example/articles/multiple"
    )

    assert result is not None
    assert result.url == "https://cdn.example/photos/article.jpg"


def test_provider_image_has_highest_priority() -> None:
    """Provider가 이미 준 이미지는 추가 HTML 후보보다 우선한다."""
    result = extract_article_image_metadata(
        '<meta property="og:image" content="https://cdn.example/og.jpg">',
        page_url="https://news.example/articles/4",
        provider_image_url="https://provider.example/cover.jpg",
    )

    assert result is not None
    assert result.url == "https://provider.example/cover.jpg"
    assert result.source == "provider"


def test_http_provider_image_is_upgraded_after_https_probe() -> None:
    """Provider HTTP 이미지는 HTTPS에서 실제 이미지로 응답할 때만 사용한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        """승격된 이미지 URL의 MIME 응답을 반환한다."""
        assert str(request.url) == "https://cdn.example/provider.jpg"
        return httpx.Response(206, headers={"Content-Type": "image/jpeg"})

    result = fetch_article_image_metadata(
        "https://news.example/article",
        provider_image_url="http://cdn.example/provider.jpg",
        transport=httpx.MockTransport(handler),
        host_resolver=lambda host: ["8.8.8.8"],
    )

    assert result is not None
    assert result.url == "https://cdn.example/provider.jpg"
    assert result.upgraded_from_http is True


def test_failed_http_provider_falls_back_to_secure_open_graph() -> None:
    """Provider HTTPS 승격이 실패하면 같은 원문의 다음 보안 후보를 사용한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        """승격 후보는 실패시키고 기사 HTML에는 보안 Open Graph를 제공한다."""
        if request.url.host == "cdn.example":
            return httpx.Response(404)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            text=(
                '<meta property="og:image:secure_url" '
                'content="https://images.example/secure.jpg">'
            ),
        )

    result = fetch_article_image_metadata(
        "https://news.example/article",
        provider_image_url="http://cdn.example/provider.jpg",
        transport=httpx.MockTransport(handler),
        host_resolver=lambda host: ["8.8.8.8"],
    )

    assert result is not None
    assert result.url == "https://images.example/secure.jpg"
    assert result.source == "open_graph"


def test_failed_http_open_graph_falls_back_to_twitter_image() -> None:
    """HTTP Open Graph 승격이 실패하면 같은 원문의 Twitter 이미지를 선택한다."""
    html = (
        '<meta property="og:image" content="http://legacy.example/cover.jpg">'
        '<meta name="twitter:image" content="https://cdn.example/twitter.jpg">'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        """기사 HTML과 실패하는 승격 이미지 응답을 구분해 반환한다."""
        if request.url.host == "news.example":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text=html,
            )
        return httpx.Response(404)

    result = fetch_article_image_metadata(
        "https://news.example/article",
        transport=httpx.MockTransport(handler),
        host_resolver=lambda host: ["8.8.8.8"],
    )

    assert result is not None
    assert result.url == "https://cdn.example/twitter.jpg"
    assert result.source == "twitter_card"


def test_failed_http_body_image_falls_back_to_next_secure_body_image() -> None:
    """본문 HTTP 이미지 승격 실패도 다음 HTTPS 본문 이미지 선택을 막지 않는다."""
    html = """
    <article>
      <img src="http://legacy.example/large.jpg" width="1200" height="800">
      <img src="https://cdn.example/next.jpg" width="1000" height="700">
    </article>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """기사 HTML을 제공하고 승격 이미지 요청은 실패시킨다."""
        if request.url.host == "news.example":
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                text=html,
            )
        return httpx.Response(404)

    result = fetch_article_image_metadata(
        "https://news.example/article",
        transport=httpx.MockTransport(handler),
        host_resolver=lambda host: ["8.8.8.8"],
    )

    assert result is not None
    assert result.url == "https://cdn.example/next.jpg"
    assert result.source == "article_dom"


def test_fetch_article_image_reads_only_html_metadata() -> None:
    """직접 HTML 요청으로 대표 이미지를 추출하고 요청 헤더를 제한한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Open Graph가 든 HTML 응답을 반환한다."""
        assert request.headers["accept"].startswith("text/html")
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            text=(
                '<meta property="og:image" '
                'content="https://cdn.example/direct.jpg">'
            ),
            request=request,
        )

    result = fetch_article_image_metadata(
        "https://news.example/article",
        transport=httpx.MockTransport(handler),
        host_resolver=lambda host: ["8.8.8.8"],
    )

    assert result is not None
    assert result.url == "https://cdn.example/direct.jpg"


def test_fetch_article_image_rejects_private_network_url() -> None:
    """원본 HTML 직접 요청은 localhost·사설 IP에 접근하지 않는다."""

    def handler(request: httpx.Request) -> httpx.Response:
        """보안 검증 전에 네트워크가 호출되면 테스트를 실패시킨다."""
        raise AssertionError("사설 주소로 HTTP 요청을 보내면 안 됩니다.")

    with pytest.raises(ArticleImageFetchError) as excinfo:
        fetch_article_image_metadata(
            "http://127.0.0.1/internal",
            transport=httpx.MockTransport(handler),
        )

    assert excinfo.value.error_code == "unsafe_url"
