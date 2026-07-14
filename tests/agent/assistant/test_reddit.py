"""Reddit 검색·게시글 요약(reddit) 검증. 실제 네트워크/LLM은 호출하지 않는다."""

from agent.assistant import reddit


def test_summarize_post_uses_selftext_and_comments(monkeypatch) -> None:
    """본문과 댓글을 합쳐 요약 함수에 넘긴다."""
    captured: dict[str, str] = {}

    def fake_summarize(text, instruction, model="gpt-4.1-mini"):
        captured["text"] = text
        return "요약 결과"

    monkeypatch.setattr(reddit, "fetch_comments", lambda permalink, max_comments=8: ["댓글1", "댓글2"])
    monkeypatch.setattr(reddit, "summarize_text", fake_summarize)

    post = {"title": "제목", "url": "u", "subreddit": "python", "score": 10, "num_comments": 2, "permalink": "/r/python/1", "selftext": "본문 내용"}
    result = reddit.summarize_post(post)

    assert result["summary"] == "요약 결과"
    assert result["note"] is None
    assert "본문 내용" in captured["text"]
    assert "댓글1" in captured["text"]


def test_summarize_post_notes_when_no_content(monkeypatch) -> None:
    """본문도 댓글도 없으면 요약 대신 안내 문구를 넣는다."""
    monkeypatch.setattr(reddit, "fetch_comments", lambda permalink, max_comments=8: [])

    called = {"summarize": False}

    def fail_summarize(*args, **kwargs):
        called["summarize"] = True
        return "should not run"

    monkeypatch.setattr(reddit, "summarize_text", fail_summarize)

    post = {"title": "링크 글", "url": "u", "subreddit": "news", "permalink": "/r/news/1", "selftext": ""}
    result = reddit.summarize_post(post)

    assert result["summary"] is None
    assert "댓글" in result["note"]
    assert called["summarize"] is False


def test_reddit_digest_maps_search_to_summaries(monkeypatch) -> None:
    """검색된 게시글 각각을 요약으로 변환한다."""
    monkeypatch.setattr(
        reddit,
        "search_posts",
        lambda keyword, limit=4: [
            {"title": "글1", "url": "u1", "subreddit": "s1", "permalink": "/r/s1/1", "selftext": "본문1"},
            {"title": "글2", "url": "u2", "subreddit": "s2", "permalink": "/r/s2/2", "selftext": "본문2"},
        ],
    )
    monkeypatch.setattr(reddit, "fetch_comments", lambda permalink, max_comments=8: [])
    monkeypatch.setattr(reddit, "summarize_text", lambda text, instruction, model="gpt-4.1-mini": "요약")

    digest = reddit.reddit_digest("키워드", limit=2)

    assert len(digest) == 2
    assert digest[0]["title"] == "글1"
    assert digest[0]["summary"] == "요약"


def test_search_posts_parses_listing(monkeypatch) -> None:
    """Reddit search.json 응답을 게시글 딕셔너리로 파싱한다."""

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "children": [
                        {"data": {"id": "abc", "title": "제목", "permalink": "/r/test/comments/abc/", "url": "https://x", "subreddit": "test", "score": 5, "num_comments": 3, "selftext": "본문"}}
                    ]
                }
            }

    import httpx

    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: FakeResponse())

    posts = reddit.search_posts("키워드", limit=1)

    assert len(posts) == 1
    assert posts[0]["title"] == "제목"
    assert posts[0]["url"] == "https://www.reddit.com/r/test/comments/abc/"
    assert posts[0]["subreddit"] == "test"


def test_fetch_comments_returns_empty_on_error(monkeypatch) -> None:
    """댓글 조회가 실패하면 빈 리스트를 반환한다."""
    import httpx

    def boom(*args, **kwargs):
        raise httpx.HTTPError("network down")

    monkeypatch.setattr(httpx, "get", boom)

    assert reddit.fetch_comments("/r/test/1") == []
