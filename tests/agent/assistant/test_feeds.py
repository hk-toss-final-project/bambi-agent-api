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


def test_fetch_provider_entries_merges_sources_and_isolates_failure() -> None:
    """여러 Provider 결과를 entry 형태로 합치고, 실패한 Provider는 건너뛴다."""
    from datetime import datetime

    from infrastructure.sources.connectors.api import LatestArticle

    class _OkProvider:
        name = "google_news"

        async def search(self, *, query, limit, language):
            return [
                LatestArticle(
                    provider=self.name,
                    title="코스피 급락",
                    url="https://news.google.com/rss/articles/a",
                    description="요약",
                    published_at=datetime(2026, 7, 23, 9, 0, tzinfo=UTC),
                    source_name="매일경제",
                    source_url="https://maeil.com",
                )
            ]

    class _BoomProvider:
        name = "naver"

        async def search(self, *, query, limit, language):
            raise RuntimeError("네트워크 오류")

    entries = feeds.fetch_provider_entries(
        "코스피", providers=[_OkProvider(), _BoomProvider()]
    )

    assert len(entries) == 1
    entry = entries[0]
    assert entry["title"] == "코스피 급락"
    assert entry["link"] == "https://news.google.com/rss/articles/a"
    assert entry["summary"] == "요약"
    assert entry["source_url"] == "https://maeil.com"  # 신뢰도 판정용 발행처
    assert entry["published_ts"] == int(
        datetime(2026, 7, 23, 9, 0, tzinfo=UTC).timestamp()
    )


def test_fetch_provider_entries_defaults_published_ts_to_zero() -> None:
    """발행 시각을 모르는 기사는 published_ts 0으로 최신성 컷에서 걸러지게 한다."""
    from infrastructure.sources.connectors.api import LatestArticle

    class _NoDateProvider:
        name = "gdelt"

        async def search(self, *, query, limit, language):
            return [
                LatestArticle(
                    provider=self.name,
                    title="날짜 없는 기사",
                    url="https://n.example/1",
                    description="",
                )
            ]

    entries = feeds.fetch_provider_entries("AI", providers=[_NoDateProvider()])

    assert entries[0]["published_ts"] == 0
    assert entries[0]["published"] == ""


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


def test_fetch_article_image_reads_and_extracts_jina_image(monkeypatch) -> None:
    """기사 이미지 조회는 Jina 원문에서 대표 이미지 한 건만 반환한다."""
    monkeypatch.setattr(
        feeds,
        "jina_read",
        lambda url: (
            "Image 1: https://cdn.example/danang.jpg\n"
            "Markdown Content:\n다낭 기사 본문"
        ),
    )

    assert feeds.fetch_article_image("https://news.example/danang") == (
        "https://cdn.example/danang.jpg"
    )


def test_jina_read_delegates_to_shared_connector(monkeypatch) -> None:
    """jina_read는 공유 Jina 커넥터에 위임하고 실패 시 None을 반환한다."""
    from infrastructure.sources.connectors import api as connectors_api

    monkeypatch.setattr(
        connectors_api,
        "fetch_url_raw_via_jina",
        lambda url, timeout: f"Markdown Content:\n{url} 본문",
    )
    assert feeds.jina_read("https://news.example/1") == (
        "Markdown Content:\nhttps://news.example/1 본문"
    )

    def boom(url, timeout):
        raise connectors_api.JinaReadError("network_error", "실패")

    monkeypatch.setattr(connectors_api, "fetch_url_raw_via_jina", boom)
    assert feeds.jina_read("https://news.example/1") is None
