"""Reddit 검색·게시글 요약(reddit) 검증. 실제 네트워크/LLM은 호출하지 않는다.

Reddit의 비공식 JSON API는 상시 차단되어 search.rss(feedparser)로 전환했다.
"""

import pytest

from agent.assistant import reddit


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch):
    """지연·재시도 대기를 0으로 만들고, 검색 캐시를 테스트마다 비운다."""
    monkeypatch.setattr(reddit, "_REQUEST_DELAY_SECONDS", 0)
    monkeypatch.setattr(reddit.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(reddit, "_search_cache", {})


def test_strip_html_removes_tags_and_collapses_whitespace() -> None:
    """HTML 태그를 제거하고 공백을 정리한다."""
    assert reddit._strip_html("<p>제목</p>  <b>본문</b>") == "제목 본문"


def test_summarize_post_summarizes_when_body_exists(monkeypatch) -> None:
    """본문이 있으면 요약 함수를 호출해 summary를 채운다."""
    captured: dict[str, str] = {}

    def fake_summarize(text, instruction, model="gpt-4.1-mini"):
        captured["text"] = text
        return "요약 결과"

    monkeypatch.setattr(reddit, "summarize_text", fake_summarize)

    post = {"title": "제목", "url": "u", "subreddit": "python", "body": "본문 내용"}
    result = reddit.summarize_post(post)

    assert result["summary"] == "요약 결과"
    assert result["note"] is None
    assert captured["text"] == "본문 내용"


def test_summarize_post_notes_when_no_body(monkeypatch) -> None:
    """본문이 없으면 요약 대신 안내 문구를 넣는다."""
    called = {"summarize": False}

    def fail_summarize(*args, **kwargs):
        called["summarize"] = True
        return "should not run"

    monkeypatch.setattr(reddit, "summarize_text", fail_summarize)

    post = {"title": "링크 글", "url": "u", "subreddit": "news", "body": ""}
    result = reddit.summarize_post(post)

    assert result["summary"] is None
    assert "본문" in result["note"]
    assert called["summarize"] is False


def test_reddit_digest_maps_search_to_summaries(monkeypatch) -> None:
    """검색된 게시글 각각을 요약으로 변환한다."""
    monkeypatch.setattr(
        reddit,
        "search_posts",
        lambda keyword, limit=4: [
            {"title": "글1", "url": "u1", "subreddit": "s1", "body": "본문1"},
            {"title": "글2", "url": "u2", "subreddit": "s2", "body": "본문2"},
        ],
    )
    monkeypatch.setattr(reddit, "summarize_text", lambda text, instruction, model="gpt-4.1-mini": "요약")

    digest = reddit.reddit_digest("키워드", limit=2)

    assert len(digest) == 2
    assert digest[0]["title"] == "글1"
    assert digest[0]["summary"] == "요약"


def test_search_posts_raises_on_rate_limit_status(monkeypatch) -> None:
    """429 같은 실패 상태를 '결과 없음'으로 조용히 숨기지 않고 예외로 알린다."""

    class FakeParsed(dict):
        entries: list = []

    def fake_parse(url, request_headers=None):
        return FakeParsed(status=429)

    monkeypatch.setattr("feedparser.parse", fake_parse)

    with pytest.raises(RuntimeError):
        reddit.search_posts("키워드", limit=2)


def test_search_posts_retries_after_rate_limit_then_succeeds(monkeypatch) -> None:
    """429를 받으면 x-ratelimit-reset만큼 기다린 뒤 재시도해 성공 결과를 반환한다."""

    class FakeEntry(dict):
        pass

    fake_entry = FakeEntry(
        id="id1", title="제목", link="https://www.reddit.com/r/test/comments/1/",
        summary="to <a href='...'>r/test</a>", content=[{"value": "본문"}],
    )

    class FakeParsed(dict):
        pass

    call_count = {"n": 0}
    sleep_calls: list[float] = []
    monkeypatch.setattr(reddit.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    def fake_parse(url, request_headers=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            parsed = FakeParsed(status=429, headers={"x-ratelimit-reset": "12"})
            parsed.entries = []
            return parsed
        parsed = FakeParsed(status=200)
        parsed.entries = [fake_entry]
        return parsed

    monkeypatch.setattr("feedparser.parse", fake_parse)

    posts = reddit.search_posts("키워드", limit=1, yesterday_only=False)

    assert call_count["n"] == 2
    assert sleep_calls == [12.0]
    assert posts[0]["title"] == "제목"


def test_search_posts_raises_after_second_failure(monkeypatch) -> None:
    """재시도까지 실패하면 예외를 그대로 던진다."""

    class FakeParsed(dict):
        entries: list = []

    def fake_parse(url, request_headers=None):
        return FakeParsed(status=429)

    monkeypatch.setattr("feedparser.parse", fake_parse)

    with pytest.raises(RuntimeError):
        reddit.search_posts("다른 키워드", limit=1)


def test_search_posts_caches_repeated_keyword(monkeypatch) -> None:
    """짧은 시간 내 같은 키워드 재검색은 새 요청 없이 캐시를 반환한다."""

    class FakeEntry(dict):
        pass

    fake_entry = FakeEntry(
        id="id1", title="글", link="https://www.reddit.com/r/test/comments/1/",
        summary="to <a href='...'>r/test</a>", content=[{"value": "본문"}],
    )

    call_count = {"n": 0}

    def fake_parse(url, request_headers=None):
        call_count["n"] += 1

        class FakeParsed(dict):
            pass

        parsed = FakeParsed(status=200)
        parsed.entries = [fake_entry]
        return parsed

    monkeypatch.setattr("feedparser.parse", fake_parse)

    first = reddit.search_posts("캐시 키워드", limit=1, yesterday_only=False)
    second = reddit.search_posts("캐시 키워드", limit=1, yesterday_only=False)

    assert call_count["n"] == 1  # 두 번째 호출은 Reddit에 다시 요청하지 않음
    assert first == second


def test_search_posts_keeps_only_yesterday_by_default(monkeypatch) -> None:
    """기본값(yesterday_only=True)은 어제 작성된 게시글만 남긴다."""
    from datetime import datetime, timedelta

    from agent.assistant import feeds

    now = datetime(2026, 7, 14, 9, 0, tzinfo=feeds._ARTICLE_TIMEZONE)
    yesterday = now - timedelta(days=1)
    two_days_ago = now - timedelta(days=2)

    def make_entry(title, published_dt):
        entry = {
            "id": title, "title": title, "link": f"https://www.reddit.com/{title}/",
            "summary": "to <a href='...'>r/test</a>", "content": [{"value": "본문"}],
        }
        if published_dt is not None:
            entry["published"] = published_dt.isoformat()
            entry["published_parsed"] = published_dt.utctimetuple()
        return entry

    class FakeParsed(dict):
        pass

    captured_urls: list[str] = []

    def fake_parse(url, request_headers=None):
        captured_urls.append(url)
        parsed = FakeParsed(status=200)
        parsed.entries = [
            make_entry("오늘글", now),
            make_entry("어제글", yesterday),
            make_entry("그저께글", two_days_ago),
            make_entry("날짜없음", None),
        ]
        return parsed

    monkeypatch.setattr("feedparser.parse", fake_parse)

    posts = reddit.search_posts("키워드", limit=5, reference_now=now)

    assert [p["title"] for p in posts] == ["어제글"]
    assert "sort=new" in captured_urls[0]  # 어제 글을 놓치지 않게 최신순으로 요청


def test_search_posts_parses_feed_entries(monkeypatch) -> None:
    """search.rss 파싱 결과를 게시글 딕셔너리로 변환한다."""

    class FakeEntry(dict):
        pass

    fake_entry = FakeEntry(
        id="https://www.reddit.com/t3_abc",
        title="제목",
        link="https://www.reddit.com/r/test/comments/abc/",
        summary=(
            "<div class='md'><p>본문 내용</p></div> submitted by "
            "<a href='...'>u/someone</a> to <a href='https://www.reddit.com/r/test/'>r/test</a>"
        ),
        content=[{"type": "text/html", "value": "<div class='md'><p>본문 내용</p></div>"}],
    )

    class FakeParsed(dict):
        entries = [fake_entry]

    def fake_parse(url, request_headers=None):
        assert "q=" in url
        assert request_headers is not None
        return FakeParsed(status=200)

    monkeypatch.setattr("feedparser.parse", fake_parse)

    posts = reddit.search_posts("키워드", limit=1, yesterday_only=False)

    assert len(posts) == 1
    assert posts[0]["title"] == "제목"
    assert posts[0]["subreddit"] == "test"
    assert "본문 내용" in posts[0]["body"]
