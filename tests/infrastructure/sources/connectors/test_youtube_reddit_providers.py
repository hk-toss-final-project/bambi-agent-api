"""YouTube·Reddit 수집 Provider 검증. 실제 네트워크는 호출하지 않는다."""

import asyncio
from datetime import UTC, datetime

import pytest

from infrastructure.sources.connectors.api import (
    LatestArticle,
    LatestProviderError,
    col_005,
)
from infrastructure.sources.connectors.features import reddit as reddit_provider
from infrastructure.sources.connectors.features import youtube as youtube_provider


# ── YouTube ───────────────────────────────────────────────────────────────


def test_relative_age_hours_parses_english_and_korean() -> None:
    """영문·국문 상대 표현을 모두 경과 시간으로 환산한다."""
    assert youtube_provider.relative_age_hours("3 hours ago") == 3.0
    assert youtube_provider.relative_age_hours("2 days ago") == 48.0
    assert youtube_provider.relative_age_hours("an hour ago") == 1.0
    assert youtube_provider.relative_age_hours("5시간 전") == 5.0
    assert youtube_provider.relative_age_hours("3일 전") == 72.0
    assert youtube_provider.relative_age_hours("알 수 없음") is None
    assert youtube_provider.relative_age_hours("") is None


def test_youtube_search_normalizes_results(monkeypatch) -> None:
    """검색 결과를 공통 최신 문서로 정규화한다."""

    class _FakeSearch:
        def __init__(self, query, limit):
            pass

        def result(self):
            return {
                "result": [
                    {
                        "id": "abc12345678",
                        "title": "코스피 급락 분석",
                        "link": "https://www.youtube.com/watch?v=abc12345678",
                        "channel": {"name": "경제채널"},
                        "publishedTime": "3 hours ago",
                    }
                ]
            }

    import sys
    import types

    module = types.ModuleType("youtubesearchpython")
    module.VideosSearch = _FakeSearch
    monkeypatch.setitem(sys.modules, "youtubesearchpython", module)

    articles = asyncio.run(
        youtube_provider.YouTubeSearchProvider().search(query="코스피", limit=1, language=None)
    )

    assert len(articles) == 1
    article = articles[0]
    assert article.provider == "youtube"
    assert article.title == "코스피 급락 분석"
    assert article.source_name == "경제채널"
    # 상대 표현이 발행 시각으로 환산된다(약 3시간 전).
    assert article.published_at is not None
    age_hours = (datetime.now(UTC) - article.published_at).total_seconds() / 3600
    assert 2.9 < age_hours < 3.1


def test_youtube_search_skips_items_without_link(monkeypatch) -> None:
    """링크 없는 항목은 건너뛴다."""

    class _FakeSearch:
        def __init__(self, query, limit):
            pass

        def result(self):
            return {"result": [{"id": "x", "title": "링크 없음", "link": ""}]}

    import sys
    import types

    module = types.ModuleType("youtubesearchpython")
    module.VideosSearch = _FakeSearch
    monkeypatch.setitem(sys.modules, "youtubesearchpython", module)

    assert (
        asyncio.run(
            youtube_provider.YouTubeSearchProvider().search(
                query="x", limit=1, language=None
            )
        )
        == []
    )


def test_youtube_search_uses_custom_search_for_sort_options(monkeypatch) -> None:
    """업로드 기간·정렬을 지정하면 CustomSearch에 환경설정 문자열을 넘긴다.

    관련도순 기본 검색은 무명 채널의 저조회수 영상과 오래된 영상을 함께
    돌려주므로(2026-07-29 실측), 수집 경로는 이 정렬 조건을 쓴다.
    """
    captured: dict[str, object] = {}

    class _FakeCustomSearch:
        def __init__(self, query, preferences, limit):
            captured["query"] = query
            captured["preferences"] = preferences
            captured["limit"] = limit

        def result(self):
            return {"result": []}

    class _UnexpectedVideosSearch:
        def __init__(self, query, limit):
            raise AssertionError("정렬 조건이 있으면 VideosSearch를 쓰면 안 된다")

    import sys
    import types

    module = types.ModuleType("youtubesearchpython")
    module.CustomSearch = _FakeCustomSearch
    module.VideosSearch = _UnexpectedVideosSearch
    module.VideoUploadDateFilter = types.SimpleNamespace(thisWeek="&sp=WEEK")
    module.VideoSortOrder = types.SimpleNamespace(viewCount="VIEWS")
    monkeypatch.setitem(sys.modules, "youtubesearchpython", module)

    provider = youtube_provider.YouTubeSearchProvider(
        upload_window="thisWeek", sort_by="viewCount"
    )
    asyncio.run(provider.search(query="AI 반도체", limit=5, language=None))

    assert captured["query"] == "AI 반도체"
    # 두 상수를 이어 붙인 하나의 환경설정 문자열을 넘긴다.
    assert captured["preferences"] == "&sp=WEEKVIEWS"
    assert captured["limit"] == 5


def test_youtube_rejects_unknown_search_options() -> None:
    """지원하지 않는 정렬 값은 조용히 무시하지 않고 거부한다."""
    with pytest.raises(ValueError):
        youtube_provider.YouTubeSearchProvider(upload_window="지난주")
    with pytest.raises(ValueError):
        youtube_provider.YouTubeSearchProvider(sort_by="popular")


def test_youtube_search_wraps_library_failure(monkeypatch) -> None:
    """스크래핑 라이브러리 실패를 Provider 오류로 감싼다 (조용히 삼키지 않는다)."""

    class _FakeSearch:
        def __init__(self, query, limit):
            raise RuntimeError("스크래핑 실패")

    import sys
    import types

    module = types.ModuleType("youtubesearchpython")
    module.VideosSearch = _FakeSearch
    monkeypatch.setitem(sys.modules, "youtubesearchpython", module)

    with pytest.raises(youtube_provider.LatestProviderError):
        asyncio.run(
            youtube_provider.YouTubeSearchProvider().search(
                query="x", limit=1, language=None
            )
        )


# ── Reddit ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_reddit_cache(monkeypatch):
    """Provider 캐시를 테스트마다 비운다."""
    monkeypatch.setattr(reddit_provider, "_search_cache", {})


class _FakeParsed(dict):
    """feedparser 응답 흉내. dict 조회(status)와 속성 접근(.entries)을 모두 지원한다."""

    entries: list = []


def _feed(entries, status=200):
    """feedparser 응답 흉내를 만든다."""
    parsed = _FakeParsed(status=status, headers={})
    parsed.entries = entries
    return parsed


def test_reddit_search_normalizes_results(monkeypatch) -> None:
    """RSS 항목을 공통 최신 문서로 정규화하고 서브레딧을 뽑는다."""
    entry = {
        "id": "t3_1",
        "title": "코스피 이야기",
        "link": "https://www.reddit.com/r/kr/comments/1",
        "summary": '<a href="x">to <a href="y">r/investing</a>',
        "published_parsed": (2026, 7, 20, 9, 0, 0, 0, 0, 0),
        "content": [{"value": "<p>본문 내용</p>"}],
    }
    monkeypatch.setattr("feedparser.parse", lambda url, request_headers=None: _feed([entry]))

    articles = asyncio.run(
        reddit_provider.RedditSearchProvider().search(query="코스피", limit=5, language=None)
    )

    assert len(articles) == 1
    article = articles[0]
    assert article.provider == "reddit"
    assert article.source_name == "r/investing"
    assert article.description == "본문 내용"      # HTML 태그 제거됨
    assert article.published_at is not None


def test_reddit_search_uses_cache_for_repeated_query(monkeypatch) -> None:
    """같은 검색은 캐시를 써서 새 요청을 만들지 않는다 (레이트리밋 보호)."""
    calls: list[str] = []

    def fake_parse(url, request_headers=None):
        calls.append(url)
        return _feed([])

    monkeypatch.setattr("feedparser.parse", fake_parse)
    provider = reddit_provider.RedditSearchProvider()

    asyncio.run(provider.search(query="코스피", limit=5, language=None))
    asyncio.run(provider.search(query="코스피", limit=5, language=None))

    assert len(calls) == 1                          # 두 번째는 캐시


def test_reddit_search_raises_after_retry_fails(monkeypatch) -> None:
    """재시도까지 실패하면 오류를 던진다 (결과 없음으로 숨기지 않는다)."""
    monkeypatch.setattr(reddit_provider.time, "sleep", lambda seconds: None)
    monkeypatch.setattr("feedparser.parse", lambda url, request_headers=None: _feed([], status=429))

    with pytest.raises(reddit_provider.LatestProviderError):
        asyncio.run(
            reddit_provider.RedditSearchProvider().search(
                query="코스피", limit=5, language=None
            )
        )


def test_reddit_restricts_search_to_configured_subreddits(monkeypatch) -> None:
    """서브레딧을 지정하면 다중 서브레딧 검색 URL을 한 번만 요청한다.

    범위를 좁히지 않으면 Reddit 전체에서 주제와 무관한 개인 글이 들어온다.
    다중 서브레딧(r/a+b)을 쓰므로 서브레딧 수만큼 요청이 늘지 않는다.
    """
    calls: list[str] = []

    def fake_parse(url, request_headers=None):
        calls.append(url)
        return _feed([])

    monkeypatch.setattr("feedparser.parse", fake_parse)
    provider = reddit_provider.RedditSearchProvider(
        subreddits=("MachineLearning", "r/programming")
    )

    asyncio.run(provider.search(query="AI chip", limit=5, language=None))

    assert len(calls) == 1
    url = calls[0]
    assert url.startswith("https://www.reddit.com/r/MachineLearning+programming/search.rss?")
    assert "restrict_sr=1" in url                    # 없으면 전체 검색으로 샌다
    assert "sort=top" in url and "t=week" in url


def test_reddit_omits_time_filter_for_new_sort(monkeypatch) -> None:
    """기간은 점수 기준 정렬에서만 붙인다 (sort=new에는 의미가 없다)."""
    calls: list[str] = []
    monkeypatch.setattr(
        "feedparser.parse",
        lambda url, request_headers=None: (calls.append(url), _feed([]))[1],
    )

    asyncio.run(
        reddit_provider.RedditSearchProvider(sort="new").search(
            query="x", limit=5, language=None
        )
    )

    assert "sort=new" in calls[0]
    assert "&t=" not in calls[0]


def test_reddit_cache_separates_different_search_scopes(monkeypatch) -> None:
    """검색 범위가 다르면 캐시를 공유하지 않는다 (다른 결과를 돌려줘야 한다)."""
    calls: list[str] = []
    monkeypatch.setattr(
        "feedparser.parse",
        lambda url, request_headers=None: (calls.append(url), _feed([]))[1],
    )

    asyncio.run(
        reddit_provider.RedditSearchProvider(subreddits=("investing",)).search(
            query="코스피", limit=5, language=None
        )
    )
    asyncio.run(
        reddit_provider.RedditSearchProvider(subreddits=("stocks",)).search(
            query="코스피", limit=5, language=None
        )
    )

    assert len(calls) == 2


def test_reddit_rejects_unknown_sort_options() -> None:
    """지원하지 않는 정렬·기간은 거부한다."""
    with pytest.raises(ValueError):
        reddit_provider.RedditSearchProvider(sort="best")
    with pytest.raises(ValueError):
        reddit_provider.RedditSearchProvider(time_filter="2주")


def test_reddit_falls_back_to_url_for_subreddit(monkeypatch) -> None:
    """요약 HTML에서 서브레딧을 못 찾으면 permalink URL에서 뽑는다.

    Reddit이 요약 HTML 구조를 바꾸면 정규식이 깨지는데, URL의 /r/<이름>/ 형태는
    안정적이라 폴백으로 쓴다(실측: 요약에서 못 뽑혀 None이 나오던 경우가 있었다).
    """
    entry = {
        "title": "글",
        "link": "https://www.reddit.com/r/StockMarket/comments/abc/foo/",
        "summary": "<p>구조가 바뀐 요약</p>",     # 서브레딧 패턴 없음
        "published_parsed": (2026, 7, 20, 9, 0, 0, 0, 0, 0),
    }
    monkeypatch.setattr("feedparser.parse", lambda url, request_headers=None: _feed([entry]))

    articles = asyncio.run(
        reddit_provider.RedditSearchProvider().search(query="x", limit=5, language=None)
    )

    assert articles[0].source_name == "r/StockMarket"


# ── COL-005 (SNS 수집 커넥터) ──────────────────────────────────────────────


class _NamedProvider:
    """이름만 다른 Provider 대역. 검색 인자를 기록한다."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[dict] = []

    async def search(self, *, query: str, limit: int, language: str | None):
        """검색 인자를 기록하고 문서 한 건을 돌려준다."""
        self.calls.append({"query": query, "limit": limit, "language": language})
        return [
            LatestArticle(
                provider=self.name,
                title="제목",
                url="https://example.com/1",
                description="",
            )
        ]


def test_col_005_collects_from_sns_providers() -> None:
    """COL-005가 YouTube·Reddit Provider에 그대로 위임하는지 검증한다."""
    for name in ("youtube", "reddit"):
        provider = _NamedProvider(name)

        articles = asyncio.run(
            col_005(provider, query="후쿠오카", limit=5, language="ko")
        )

        assert [article.provider for article in articles] == [name]
        assert provider.calls == [{"query": "후쿠오카", "limit": 5, "language": "ko"}]


def test_col_005_rejects_non_sns_provider() -> None:
    """SNS가 아닌 Provider를 넘기면 거부하는지 검증한다."""
    with pytest.raises(LatestProviderError):
        asyncio.run(
            col_005(_NamedProvider("naver"), query="코스피", limit=5, language="ko")
        )
