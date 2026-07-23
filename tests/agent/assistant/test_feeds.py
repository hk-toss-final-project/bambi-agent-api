"""RSS 수집·정제·최신성 필터·중복 제거(feeds) 검증. 실제 네트워크는 호출하지 않는다."""

from datetime import UTC, datetime, timedelta

import pytest

from agent.assistant.features import feeds


@pytest.fixture(autouse=True)
def _mock_llm_summary(monkeypatch):
    """기사 요약 LLM 호출을 결정적 mock으로 대체해 실제 호출을 막는다."""
    monkeypatch.setattr(
        "agent.assistant.features.summarize.summarize_text",
        lambda text, instruction, model="gpt-4.1-mini": f"요약<{text[:20]}>",
    )

_NOW = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
_YESTERDAY = _NOW - timedelta(days=1)
_TWO_DAYS_AGO = _NOW - timedelta(days=2)


def _ts(dt: datetime) -> int:
    """테스트용 datetime을 published_ts(UTC epoch 초)로 변환한다."""
    return int(dt.timestamp())


def test_build_news_feed_url_encodes_keyword() -> None:
    """키워드가 URL 인코딩되어 Google News 검색 피드 주소에 들어간다."""
    url = feeds.build_news_feed_url("전고체 배터리")
    assert "news.google.com/rss/search" in url
    assert "%EC" in url or "+" in url  # 한글이 인코딩됨


def test_extract_source_reads_publisher_from_rss() -> None:
    """RSS의 <source> 요소에서 원본 발행처 URL과 이름을 뽑는다.

    Google News의 link는 자기네 리다이렉트 주소라 발행처를 알 수 없고, 이 필드가
    유일하게 진짜 언론사 도메인을 알려준다.
    """
    entry = {"source": {"href": "https://www.chosun.com", "title": "조선일보"}}
    assert feeds._extract_source(entry) == ("https://www.chosun.com", "조선일보")


def test_extract_source_returns_empty_when_absent() -> None:
    """<source>가 없는 피드 항목은 빈 문자열을 반환한다 (예외를 내지 않는다)."""
    assert feeds._extract_source({}) == ("", "")
    assert feeds._extract_source({"source": None}) == ("", "")


def test_canonical_url_strips_query_and_fragment() -> None:
    """query와 fragment를 제거하고 host를 소문자화한다."""
    assert feeds.canonical_url("https://A.com/news/1?utm=x#top") == "https://a.com/news/1"


def test_deduplicate_keeps_latest_and_removes_duplicate_url() -> None:
    """같은 정규 URL은 더 최신 항목만 남긴다."""
    entries = [
        {"title": "옛날", "link": "https://a.com/1?ref=old", "published_ts": 100},
        {"title": "최신", "link": "https://a.com/1?ref=new", "published_ts": 200},
        {"title": "다른 글", "link": "https://a.com/2", "published_ts": 150},
    ]
    result = feeds.deduplicate(entries)
    urls = [feeds.canonical_url(str(item["link"])) for item in result]
    assert urls == ["https://a.com/1", "https://a.com/2"]
    # 중복 URL 중 최신(200) 항목이 남았는지 확인
    assert result[0]["title"] == "최신"


def test_deduplicate_removes_duplicate_titles() -> None:
    """URL이 달라도 동일 제목이면 중복으로 제거한다."""
    entries = [
        {"title": "같은 제목", "link": "https://a.com/1", "published_ts": 200},
        {"title": "같은 제목", "link": "https://b.com/2", "published_ts": 100},
    ]
    result = feeds.deduplicate(entries)
    assert len(result) == 1


def test_filter_recent_entries_keeps_only_recent() -> None:
    """발행된 지 기준 시간(48시간) 이내인 항목만 남기고, 발행시각을 모르는 항목은 제외한다."""
    entries = [
        {"title": "오늘", "published_ts": _ts(_NOW)},
        {"title": "어제", "published_ts": _ts(_YESTERDAY)},
        {"title": "사흘 전", "published_ts": _ts(_NOW - timedelta(days=3))},
        {"title": "발행시각모름", "published_ts": 0},
    ]
    kept = [e["title"] for e in feeds.filter_recent_entries(entries, reference_now=_NOW)]
    assert kept == ["오늘", "어제"]


def test_make_snippet_strips_html_tags() -> None:
    """RSS 요약(content=None)의 HTML 태그를 제거하고 길이를 제한한다."""
    entry = {"link": "https://a.com/1", "summary": "<a href='x'>제목</a> <b>본문</b>"}
    snippet = feeds._make_snippet(entry, None)
    assert "<" not in snippet
    assert "제목" in snippet and "본문" in snippet


def test_make_snippet_cleans_jina_metadata_and_urls() -> None:
    """Jina 응답의 메타데이터 헤더와 URL을 제거하고 본문만 남긴다."""
    jina_raw = (
        "Title: 코스피 급등\n"
        "URL Source: https://news.example/1\n"
        "Published Time: 2026-07-15T00:27:51+00:00\n"
        "Markdown Content:\n"
        "# [코스피](https://news.example/1)\n"
        "코스피가 외국인 매수에 7400선을 돌파했다. 자세히는 https://news.example/1 참고."
    )

    snippet = feeds._make_snippet({"link": "https://news.example/1"}, jina_raw)

    assert "URL Source" not in snippet
    assert "Markdown Content" not in snippet
    assert "http" not in snippet  # URL 제거됨
    assert "코스피가 외국인 매수에 7400선을 돌파했다" in snippet


def test_extract_jina_image_picks_content_image_over_icon() -> None:
    """헤더/본문 이미지 중 아이콘·로고는 걸러내고 대표 이미지를 뽑는다."""
    text = (
        "Image 1: https://cdn.example/logo.png\n"
        "Markdown Content:\n"
        "![hero](https://cdn.example/photos/hero-960.jpg)\n"
        "본문 텍스트"
    )
    assert feeds._extract_jina_image(text) == "https://cdn.example/photos/hero-960.jpg"


def test_extract_jina_image_returns_none_when_no_image() -> None:
    """이미지가 없으면 None을 반환한다."""
    assert feeds._extract_jina_image("Markdown Content:\n본문만 있음") is None
