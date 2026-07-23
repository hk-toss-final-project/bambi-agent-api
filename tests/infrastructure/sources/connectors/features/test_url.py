"""infrastructure/sources/connectors/features/url.py의 Jina Reader 수집 기능을 검증한다."""

import httpx
import pytest

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
