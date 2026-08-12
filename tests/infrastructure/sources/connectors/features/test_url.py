"""infrastructure/sources/connectors/features/url.py의 Jina Reader 수집 기능을 검증한다."""

import httpx
import pytest

from infrastructure.sources.connectors.features import url as url_connector
from infrastructure.sources.connectors.features.url import (
    JinaReadError,
    fetch_url_via_jina,
    parse_jina_reader_response,
)

_SAMPLE_RESPONSE = (
    "Title: KOSPI 지수 현황\n"
    "URL Source: https://finance.naver.com/sise/sise_index.naver?code=KOSPI\n"
    "Published Time: 2026-07-14T09:00:00+09:00\n"
    "Markdown Content:\n"
    "# 코스피\n\n오늘의 지수는 상승했다.\n"
)


def test_parse_jina_reader_response_extracts_headers_and_markdown() -> None:
    """헤더 3종과 Markdown 본문을 정확히 분리하는지 검증한다."""
    result = parse_jina_reader_response(
        _SAMPLE_RESPONSE, requested_url="https://finance.naver.com/short"
    )

    assert result.title == "KOSPI 지수 현황"
    assert (
        result.resolved_url
        == "https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
    )
    assert result.published_time == "2026-07-14T09:00:00+09:00"
    assert result.markdown == "# 코스피\n\n오늘의 지수는 상승했다."
    assert result.requested_url == "https://finance.naver.com/short"


def test_parse_jina_reader_response_without_marker_uses_full_text() -> None:
    """'Markdown Content:' 구분자가 없으면 전체를 본문으로 쓰고 요청 URL로 대체한다."""
    result = parse_jina_reader_response(
        "본문만 있는 응답", requested_url="https://example.com/page"
    )

    assert result.title == "https://example.com/page"
    assert result.resolved_url == "https://example.com/page"
    assert result.published_time is None
    assert result.markdown == "본문만 있는 응답"


def test_parse_jina_reader_response_rejects_empty_markdown() -> None:
    """본문이 공백뿐이면 empty_content 오류를 발생시키는지 검증한다."""
    with pytest.raises(JinaReadError) as excinfo:
        parse_jina_reader_response(
            "Title: 빈 문서\nMarkdown Content:\n   \n",
            requested_url="https://example.com/empty",
        )

    assert excinfo.value.error_code == "empty_content"


def test_fetch_url_via_jina_returns_parsed_result() -> None:
    """정상 응답이면 파싱된 결과를 반환하고 Reader 경로로 요청하는지 검증한다."""
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        assert "Authorization" not in request.headers
        return httpx.Response(200, text=_SAMPLE_RESPONSE)

    result = fetch_url_via_jina(
        "https://finance.naver.com/sise/sise_index.naver?code=KOSPI",
        api_key="",
        transport=httpx.MockTransport(handler),
    )

    assert result.title == "KOSPI 지수 현황"
    assert seen_urls == [
        "https://r.jina.ai/https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
    ]


def test_fetch_url_via_jina_sends_bearer_header_with_api_key() -> None:
    """API Key가 주어지면 Bearer 인증 헤더를 붙이는지 검증한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, text=_SAMPLE_RESPONSE)

    fetch_url_via_jina(
        "https://example.com/page",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )


def test_fetch_url_via_jina_raises_on_http_error_status() -> None:
    """4xx/5xx 상태는 상태 코드가 담긴 JinaReadError로 변환하는지 검증한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(451, text="blocked")

    with pytest.raises(JinaReadError) as excinfo:
        fetch_url_via_jina(
            "https://alphacatcherhq.slack.com/archives/C0BFYD2P4NQ/p1",
            api_key="",
            transport=httpx.MockTransport(handler),
        )

    assert excinfo.value.error_code == "http_451"


def test_fetch_url_via_jina_raises_on_network_error() -> None:
    """연결 실패 같은 전송 오류는 network_error 코드로 변환하는지 검증한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(JinaReadError) as excinfo:
        fetch_url_via_jina(
            "https://example.com/down",
            api_key="",
            transport=httpx.MockTransport(handler),
        )

    assert excinfo.value.error_code == "network_error"


def test_fetch_url_raw_via_jina_returns_full_text_with_headers() -> None:
    """원문 함수는 헤더 블록('Image N:' 등)을 잃지 않고 전문을 반환한다.

    키워드 비서의 대표 이미지 추출이 헤더에 의존하므로, 파싱 전에 원문을
    받을 수 있는 경계가 유지돼야 한다.
    """
    raw = (
        "Title: 제목\nURL Source: https://news.example/1\n"
        "Image 1: https://img.example/a.jpg\n"
        "Markdown Content:\n본문입니다."
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=raw)

    from infrastructure.sources.connectors.features.url import fetch_url_raw_via_jina

    result = fetch_url_raw_via_jina(
        "https://news.example/1", transport=httpx.MockTransport(handler)
    )

    assert result == raw


def test_parse_jina_reader_response_extracts_content_image() -> None:
    """구조화 파서는 로고를 건너뛰고 기사 본문 대표 이미지를 보존한다."""
    raw = (
        "Title: 뉴스 기사 본문 제목\nURL Source: https://news.example/1\n"
        "Image 1: https://cdn.example/logo.png\n"
        "Markdown Content:\n"
        "# 뉴스 기사 본문 제목\n"
        "![대표](https://cdn.example/photos/hero-1280.webp)\n본문입니다."
    )

    result = parse_jina_reader_response(raw, requested_url="https://news.example/1")

    assert result.image_url == "https://cdn.example/photos/hero-1280.webp"


def test_parse_jina_reader_response_prefers_image_after_article_title() -> None:
    """뉴스 메뉴 이미지가 먼저 있어도 기사 제목 뒤의 본문 사진을 선택한다."""
    raw = (
        "Title: 자연·건축·웰니스·미식, 다낭의 또 다른 휴양법\n"
        "URL Source: https://news.example/danang\n"
        "Markdown Content:\n"
        "![광고](https://menu.example/news/banner/advertisement.jpg)\n"
        "![로고](https://news.example/images/logo2024.png)\n"
        "![검색](https://news.example/images/ico_search.png)\n"
        "분야별 뉴스와 메뉴\n"
        "# 자연·건축·웰니스·미식, 다낭의 또 다른 휴양법\n"
        "![메인 로비](https://cdn.example/2026/danang-hero.jpg?rnd=1)\n"
        "다낭 리조트의 본문입니다."
    )

    result = parse_jina_reader_response(raw, requested_url="https://news.example/danang")

    assert result.image_url == "https://cdn.example/2026/danang-hero.jpg?rnd=1"


def test_parse_jina_reader_response_returns_no_image_without_title_anchor() -> None:
    """기사 제목을 본문에서 찾지 못하면 메뉴 이미지를 대표 사진으로 쓰지 않는다."""
    raw = (
        "Title: 찾을 수 없는 기사 제목\n"
        "Markdown Content:\n"
        "![광고](https://menu.example/news/banner/advertisement.jpg)\n"
        "![검색](https://news.example/images/ico_search.png)\n"
        "메뉴만 수집된 응답"
    )

    result = parse_jina_reader_response(raw, requested_url="https://news.example/broken")

    assert result.image_url is None


def test_probable_content_image_rejects_page_chrome_assets() -> None:
    """배너·아이콘·검색 버튼 URL은 본문 이미지 후보로 인정하지 않는다."""
    rejected = [
        "https://menu.example/news/banner/advertisement.jpg",
        "https://news.example/images/ico_search.png",
        "https://news.example/images/btn_more.png",
        "https://news.example/images/arrow_down.png",
    ]

    assert all(
        not url_connector.is_probable_content_image_url(url) for url in rejected
    )
    assert url_connector.is_probable_content_image_url(
        "https://cdn.example/2026/danang-hero.jpg?rnd=1"
    )


def test_resolve_article_image_replaces_cached_banner_with_body_image() -> None:
    """기존 배너 캐시는 저장된 본문 대표 이미지로 다시 계산해 교체한다."""
    markdown = (
        "![광고](https://menu.example/news/banner/advertisement.jpg)\n"
        "# 자연·건축·웰니스·미식, 다낭의 또 다른 휴양법\n"
        "![본문](https://cdn.example/2026/danang-hero.jpg)\n"
        "기사 본문입니다."
    )

    assert url_connector.resolve_article_image(
        markdown=markdown,
        title="자연·건축·웰니스·미식, 다낭의 또 다른 휴양법",
        cached_url="https://menu.example/news/banner/advertisement.jpg",
    ) == "https://cdn.example/2026/danang-hero.jpg"


def test_resolve_article_image_keeps_safe_cache_without_body_image() -> None:
    """본문 이미지가 없으면 안전한 기존 대표 이미지 URL은 유지한다."""
    assert url_connector.resolve_article_image(
        markdown="# 이미지 없는 긴 기사 제목입니다\n기사 본문입니다.",
        title="이미지 없는 긴 기사 제목입니다",
        cached_url="https://cdn.example/2026/previous-cover.jpg",
    ) == "https://cdn.example/2026/previous-cover.jpg"


def test_resolve_article_image_prefers_metadata_cache_over_jina_body_image() -> None:
    """HTML 메타데이터로 저장한 캐시는 Jina 본문 첫 이미지로 덮지 않는다."""
    markdown = (
        "# 본문 대표 이미지를 확인하는 긴 기사 제목\n"
        "![AI 아이콘](https://cdn.example/images/aichat/global_ani.png)\n"
        "![본문](https://cdn.example/photos/body.jpg)"
    )

    assert url_connector.resolve_article_image(
        markdown=markdown,
        title="본문 대표 이미지를 확인하는 긴 기사 제목",
        cached_url="https://cdn.example/photos/open-graph.jpg",
    ) == "https://cdn.example/photos/open-graph.jpg"


def test_resolve_article_image_rejects_cached_ai_widget_and_reporter_photo() -> None:
    """기존 AI 위젯 캐시는 건너뛰고 실제 기사 본문 사진을 다시 선택한다."""
    markdown = (
        "# 대한체육회, 아시안게임 응원 열기와 미디어 전략 강화\n"
        "![AI 배너](https://cdn.example/images/aichat/aichat_banner_md.png)\n"
        "![애니메이션](https://cdn.example/images/aichat/global_ani.png)\n"
        "![기자](https://cdn.example/news/column/sports.jpg)\n"
        "기사 첫 문단입니다.\n"
        "![현장](https://cdn.example/photos/article-main.jpg)"
    )

    assert url_connector.resolve_article_image(
        markdown=markdown,
        title="대한체육회, 아시안게임 응원 열기와 미디어 전략 강화",
        cached_url="https://cdn.example/images/aichat/global_ani.png",
    ) == "https://cdn.example/photos/article-main.jpg"


def test_parse_jina_reader_response_ignores_unsafe_image_url() -> None:
    """HTTP(S)가 아닌 이미지 후보는 대표 이미지로 사용하지 않는다."""
    raw = "Title: 제목\nMarkdown Content:\n![대표](data:image/png;base64,AAAA)\n본문"

    result = parse_jina_reader_response(raw, requested_url="https://news.example/1")

    assert result.image_url is None
