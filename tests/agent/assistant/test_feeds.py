"""RSS 수집·정제·날짜 필터·중복 제거(feeds) 검증. 실제 네트워크는 호출하지 않는다."""

from datetime import date, datetime, timedelta

from agent.assistant import feeds

_NOW = datetime(2026, 7, 14, 9, 0, tzinfo=feeds._ARTICLE_TIMEZONE)
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


def test_build_news_feed_url_adds_after_before_operators() -> None:
    """after/before를 주면 Google News 날짜 검색 연산자가 쿼리에 포함된다."""
    url = feeds.build_news_feed_url(
        "아이폰", after=date(2026, 7, 13), before=date(2026, 7, 14)
    )
    assert "after%3A2026-07-13" in url
    assert "before%3A2026-07-14" in url


def test_build_news_feed_url_omits_operators_when_not_given() -> None:
    """after/before를 주지 않으면 날짜 연산자가 붙지 않는다."""
    url = feeds.build_news_feed_url("아이폰")
    assert "after%3A" not in url
    assert "before%3A" not in url


def test_canonical_url_strips_query_and_fragment() -> None:
    """query와 fragment를 제거하고 host를 소문자화한다."""
    assert feeds.canonical_url("https://A.com/news/1?utm=x#top") == "https://a.com/news/1"


def test_filter_to_date_keeps_only_matching_calendar_day() -> None:
    """지정한 날짜(한국 시간 기준)에 발행된 항목만 남긴다."""
    entries = [
        {"title": "어제 아침", "published_ts": _ts(_YESTERDAY.replace(hour=1))},
        {"title": "어제 밤", "published_ts": _ts(_YESTERDAY.replace(hour=23))},
        {"title": "그저께", "published_ts": _ts(_TWO_DAYS_AGO)},
        {"title": "발행시각모름", "published_ts": 0},
    ]
    kept = [e["title"] for e in feeds.filter_to_date(entries, _YESTERDAY.date())]
    assert kept == ["어제 아침", "어제 밤"]


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


def test_latest_articles_keeps_only_yesterday_by_default(monkeypatch) -> None:
    """기본값(yesterday_only=True)은 어제 발행된 기사만 남기고 그 외는 제외한다."""

    def fake_fetch(feed_url: str) -> list[dict[str, object]]:
        return [
            {"title": "오늘 기사", "link": "https://a.com/today", "summary": "오늘", "published": "", "published_ts": _ts(_NOW)},
            {"title": "어제 기사", "link": "https://a.com/yesterday", "summary": "어제", "published": "", "published_ts": _ts(_YESTERDAY)},
            {"title": "그저께 기사", "link": "https://a.com/old", "summary": "그저께", "published": "", "published_ts": _ts(_TWO_DAYS_AGO)},
        ]

    monkeypatch.setattr(feeds, "fetch_feed_entries", fake_fetch)
    monkeypatch.setattr(feeds, "jina_read", lambda url: None)

    articles = feeds.latest_articles("키워드", limit=5, reference_now=_NOW)

    titles = [a["title"] for a in articles]
    assert titles == ["어제 기사"]


def test_latest_articles_narrows_query_with_date_operators(monkeypatch) -> None:
    """yesterday_only=True면 서버 쪽 요청 자체를 어제 하루로 좁힌다."""
    captured_urls: list[str] = []

    def fake_fetch(feed_url: str) -> list[dict[str, object]]:
        captured_urls.append(feed_url)
        return [
            {"title": "어제 기사", "link": "https://a.com/y", "summary": "", "published": "", "published_ts": _ts(_YESTERDAY)},
        ]

    monkeypatch.setattr(feeds, "fetch_feed_entries", fake_fetch)
    monkeypatch.setattr(feeds, "jina_read", lambda url: None)

    feeds.latest_articles("키워드", limit=5, reference_now=_NOW)

    assert len(captured_urls) == 1
    assert "after%3A2026-07-13" in captured_urls[0]
    assert "before%3A2026-07-14" in captured_urls[0]


def test_latest_articles_can_disable_date_filter(monkeypatch) -> None:
    """yesterday_only=False면 날짜와 무관하게 최신순으로 가져온다."""

    def fake_fetch(feed_url: str) -> list[dict[str, object]]:
        return [
            {"title": "오늘 기사", "link": "https://a.com/today", "summary": "", "published": "", "published_ts": _ts(_NOW)},
            {"title": "그저께 기사", "link": "https://a.com/old", "summary": "", "published": "", "published_ts": _ts(_TWO_DAYS_AGO)},
        ]

    monkeypatch.setattr(feeds, "fetch_feed_entries", fake_fetch)
    monkeypatch.setattr(feeds, "jina_read", lambda url: None)

    articles = feeds.latest_articles("키워드", limit=5, yesterday_only=False, reference_now=_NOW)

    titles = [a["title"] for a in articles]
    assert titles == ["오늘 기사", "그저께 기사"]


def test_latest_articles_uses_jina_for_top_items(monkeypatch) -> None:
    """상위 jina_top개는 Jina 본문을, 나머지는 RSS 요약을 요지로 쓴다."""

    def fake_fetch(feed_url: str) -> list[dict[str, object]]:
        return [
            {
                "title": "글1",
                "link": "https://a.com/1",
                "summary": "<p>RSS 요약1</p>",
                "published": "",
                "published_ts": _ts(_YESTERDAY.replace(hour=9)),
            },
            {
                "title": "글2",
                "link": "https://a.com/2",
                "summary": "RSS 요약2",
                "published": "",
                "published_ts": _ts(_YESTERDAY.replace(hour=8)),
            },
        ]

    jina_calls: list[str] = []

    def fake_jina(url: str) -> str | None:
        jina_calls.append(url)
        return "Jina 정제 본문"

    monkeypatch.setattr(feeds, "fetch_feed_entries", fake_fetch)
    monkeypatch.setattr(feeds, "jina_read", fake_jina)

    articles = feeds.latest_articles("키워드", limit=5, jina_top=1, reference_now=_NOW)

    assert len(articles) == 2
    assert articles[0]["snippet"] == "Jina 정제 본문"  # 상위 1개는 Jina 사용
    assert articles[1]["snippet"] == "RSS 요약2"  # 나머지는 RSS 요약, HTML 태그 제거됨
    assert jina_calls == ["https://a.com/1"]


def test_make_snippet_strips_html_tags(monkeypatch) -> None:
    """RSS 요약의 HTML 태그를 제거하고 길이를 제한한다."""
    monkeypatch.setattr(feeds, "jina_read", lambda url: None)
    entry = {"link": "https://a.com/1", "summary": "<a href='x'>제목</a> <b>본문</b>"}
    snippet = feeds._make_snippet(entry, use_jina=False)
    assert "<" not in snippet
    assert "제목" in snippet and "본문" in snippet
