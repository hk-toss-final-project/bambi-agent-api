"""RSS 수집·정제·중복 제거(feeds) 검증. 실제 네트워크는 호출하지 않는다."""

from agent.assistant import feeds


def test_build_news_feed_url_encodes_keyword() -> None:
    """키워드가 URL 인코딩되어 Google News 검색 피드 주소에 들어간다."""
    url = feeds.build_news_feed_url("전고체 배터리")
    assert "news.google.com/rss/search" in url
    assert "%EC" in url or "+" in url  # 한글이 인코딩됨


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


def test_latest_articles_uses_jina_for_top_items(monkeypatch) -> None:
    """상위 jina_top개는 Jina 본문을, 나머지는 RSS 요약을 요지로 쓴다."""

    def fake_fetch(feed_url: str) -> list[dict[str, object]]:
        return [
            {"title": "글1", "link": "https://a.com/1", "summary": "<p>RSS 요약1</p>", "published": "", "published_ts": 300},
            {"title": "글2", "link": "https://a.com/2", "summary": "RSS 요약2", "published": "", "published_ts": 200},
        ]

    jina_calls: list[str] = []

    def fake_jina(url: str) -> str | None:
        jina_calls.append(url)
        return "Jina 정제 본문"

    monkeypatch.setattr(feeds, "fetch_feed_entries", fake_fetch)
    monkeypatch.setattr(feeds, "jina_read", fake_jina)

    articles = feeds.latest_articles("키워드", limit=5, jina_top=1)

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
