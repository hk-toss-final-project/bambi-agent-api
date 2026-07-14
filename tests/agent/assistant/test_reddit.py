"""Reddit 검색·게시글 요약(reddit) 검증. 실제 네트워크/LLM은 호출하지 않는다.

Reddit의 비공식 JSON API는 상시 차단되어 search.rss(feedparser)로 전환했다.
"""

import pytest

from agent.assistant import reddit


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch):
    """게시글 사이 지연을 0으로 만들어 테스트가 실제로 기다리지 않게 한다."""
    monkeypatch.setattr(reddit, "_REQUEST_DELAY_SECONDS", 0)


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

    posts = reddit.search_posts("키워드", limit=1)

    assert len(posts) == 1
    assert posts[0]["title"] == "제목"
    assert posts[0]["subreddit"] == "test"
    assert "본문 내용" in posts[0]["body"]
