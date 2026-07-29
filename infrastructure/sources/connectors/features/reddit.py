"""Reddit 검색 Provider (공용 수집 커넥터).

키워드로 Reddit 게시글을 검색해 공통 최신 문서(LatestArticle)로 정규화한다.

Reddit의 비공식 JSON API(`search.json`)는 브라우저가 아닌 요청을 상시 차단해 쓸 수
없다. 대신 공개 RSS(`search.rss`)는 접근 가능해 feedparser로 파싱한다. RSS는 JSON
API보다 정보가 적어(점수·댓글 수 없음) 제목과 본문 중심으로 다룬다.

Reddit RSS는 비인증 요청에 매우 빡빡한 레이트리밋을 건다(요청 1번에
`x-ratelimit-remaining`이 0이 되고 수십 초 뒤 리셋). 그래서 두 장치를 둔다:

1. 429를 받으면 `x-ratelimit-reset`(초)만큼 기다렸다 한 번 재시도한다.
2. 같은 검색을 짧은 시간(TTL) 캐시해 반복 요청을 만들지 않는다.

재시도까지 실패하면 예외를 던진다 — 실패를 "결과 없음"으로 숨기지 않는다.

검색 범위·정렬: Reddit 전체를 최신순으로 뒤지면 주제와 무관한 개인 글이 그대로
들어온다. 그래서 두 가지를 조정할 수 있게 열어 둔다.

1. `subreddits` — 주제 커뮤니티로 범위를 좁힌다. Reddit이 `r/a+b+c` 형태의 다중
   서브레딧 검색을 지원해 한 번의 요청으로 끝난다(요청 수가 늘지 않아 레이트리밋
   에도 유리하다).
2. `sort="top"` + `time_filter` — RSS에는 점수·댓글 수가 없어 우리가 인기 글을
   고를 수 없다. 대신 Reddit에게 점수순 정렬을 시켜 그 결과를 받는다.
"""

from __future__ import annotations

import calendar
import re
import time
from datetime import UTC, datetime
from urllib.parse import quote_plus

from infrastructure.sources.connectors.features.latest import (
    LatestArticle,
    LatestProviderError,
)

_SEARCH_RSS_URL = "https://www.reddit.com/search.rss"
_SUBREDDIT_SEARCH_RSS_URL = "https://www.reddit.com/r/{subreddits}/search.rss"
# User-Agent 없는 요청을 Reddit이 더 쉽게 차단하므로 고유 값을 명시한다.
_HEADERS = {"User-Agent": "report-builder-source-connector/0.1 (keyword collection)"}

# 지정할 수 있는 정렬과 기간. Reddit search가 받는 값과 같다.
SORT_ORDERS = ("relevance", "hot", "top", "new", "comments")
TIME_FILTERS = ("hour", "day", "week", "month", "year", "all")
# 기간(t)은 점수·댓글 기준 정렬에서만 의미가 있다. new/hot에는 붙이지 않는다.
_TIME_AWARE_SORTS = ("relevance", "top", "comments")

# 429 재시도 대기. x-ratelimit-reset이 있으면 그 값을, 없으면 기본값을 쓴다.
# 요청이 너무 오래 걸리지 않도록 상한을 둔다.
_DEFAULT_RETRY_WAIT_SECONDS = 5.0
_MAX_RETRY_WAIT_SECONDS = 30.0

# 같은 검색 결과를 재사용하는 시간(초). 레이트리밋 리셋 주기보다 넉넉히 잡는다.
_CACHE_TTL_SECONDS = 90.0
_search_cache: dict[str, tuple[float, list[LatestArticle]]] = {}

_SUBREDDIT_PATTERN = re.compile(r"to\s*<a[^>]*>\s*r/([^\s<]+)")
# 요약 HTML에서 못 찾을 때의 폴백. permalink는 항상 /r/<서브레딧>/ 형태다.
_SUBREDDIT_URL_PATTERN = re.compile(r"/r/([^/]+)/")
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """HTML 태그를 제거하고 공백을 정리한다."""
    return " ".join(_HTML_TAG_PATTERN.sub(" ", text).split())


def _cache_key(query: str, limit: int, feed_url: str) -> str:
    """검색어를 대소문자·공백 차이 없이 캐시 조회할 수 있게 정규화한다.

    검색 범위·정렬이 다르면 결과도 다르므로 완성된 요청 URL을 Key에 포함한다.
    """
    return f"{' '.join(query.strip().lower().split())}::{limit}::{feed_url}"


def _fetch_feed(feed_url: str):
    """RSS 피드를 조회한다. 429면 리셋 시간만큼 기다린 뒤 한 번 재시도한다."""
    import feedparser

    parsed = feedparser.parse(feed_url, request_headers=_HEADERS)
    status = parsed.get("status")
    if status is None or status < 400:
        return parsed

    reset_header = parsed.get("headers", {}).get("x-ratelimit-reset")
    try:
        wait_seconds = min(float(reset_header), _MAX_RETRY_WAIT_SECONDS)
    except (TypeError, ValueError):
        wait_seconds = _DEFAULT_RETRY_WAIT_SECONDS
    time.sleep(wait_seconds)

    parsed = feedparser.parse(feed_url, request_headers=_HEADERS)
    status = parsed.get("status")
    if status is not None and status >= 400:
        raise LatestProviderError(
            "reddit",
            "rate_limited",
            f"Reddit search.rss 요청 실패 (status={status}). 잠시 후 다시 시도하세요.",
        )
    return parsed


class RedditSearchProvider:
    """Reddit 공개 RSS 검색 결과를 공통 최신 문서로 정규화한다.

    API Key가 필요 없다(Reddit이 자체 서비스 정책으로 자율 발급 키를 중단했다).
    대신 레이트리밋이 빡빡해 재시도·캐시를 내장한다.
    """

    name = "reddit"

    def __init__(
        self,
        *,
        subreddits: tuple[str, ...] | list[str] = (),
        sort: str = "top",
        time_filter: str = "week",
    ) -> None:
        """검색 범위와 정렬을 저장한다.

        Args:
            subreddits: 검색할 서브레딧 이름 목록 (예: ("MachineLearning", "programming")).
                비우면 Reddit 전체를 검색한다.
            sort: 정렬 기준 (SORT_ORDERS 중 하나)
            time_filter: 기간 (TIME_FILTERS 중 하나). 점수 기준 정렬에서만 쓰인다.

        Raises:
            ValueError: 지원하지 않는 정렬·기간을 넘겼을 때
        """
        if sort not in SORT_ORDERS:
            raise ValueError(
                f"지원하지 않는 sort입니다: {sort} (가능: {', '.join(SORT_ORDERS)})"
            )
        if time_filter not in TIME_FILTERS:
            raise ValueError(
                f"지원하지 않는 time_filter입니다: {time_filter} "
                f"(가능: {', '.join(TIME_FILTERS)})"
            )
        self._subreddits = tuple(
            name.strip().lstrip("r/").strip("/")
            for name in subreddits
            if name and name.strip()
        )
        self._sort = sort
        self._time_filter = time_filter

    def _feed_url(self, query: str, limit: int) -> str:
        """검색 범위·정렬을 반영한 RSS 요청 URL을 만든다."""
        parameters = [f"q={quote_plus(query)}", f"sort={self._sort}", f"limit={limit}"]
        if self._sort in _TIME_AWARE_SORTS:
            parameters.append(f"t={self._time_filter}")
        if self._subreddits:
            base = _SUBREDDIT_SEARCH_RSS_URL.format(
                subreddits="+".join(self._subreddits)
            )
            # restrict_sr이 없으면 서브레딧 경로를 무시하고 전체를 검색한다.
            parameters.append("restrict_sr=1")
        else:
            base = _SEARCH_RSS_URL
        return f"{base}?{'&'.join(parameters)}"

    async def search(
        self, *, query: str, limit: int, language: str | None
    ) -> list[LatestArticle]:
        """키워드로 게시글을 검색해 최신 문서 목록을 반환한다.

        language는 사용하지 않는다 — Reddit RSS가 언어 필터를 제공하지 않는다.
        """
        feed_url = self._feed_url(query, limit)
        cache_key = _cache_key(query, limit, feed_url)
        cached = _search_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
            return list(cached[1])

        parsed = _fetch_feed(feed_url)

        articles: list[LatestArticle] = []
        for entry in list(parsed.entries)[:limit]:
            url = str(entry.get("link") or "").strip()
            if not url:
                continue
            summary_html = str(entry.get("summary", ""))
            subreddit_match = _SUBREDDIT_PATTERN.search(summary_html)
            content = entry.get("content")
            body_html = str(content[0].get("value", "")) if content else summary_html
            published_struct = entry.get("published_parsed")
            published_at = (
                datetime.fromtimestamp(calendar.timegm(published_struct), tz=UTC)
                if published_struct
                else None
            )
            # 요약 HTML 구조는 Reddit 쪽 변경에 취약하므로, 못 찾으면 URL에서 뽑는다.
            if subreddit_match:
                subreddit = subreddit_match.group(1)
            elif url_match := _SUBREDDIT_URL_PATTERN.search(url):
                subreddit = url_match.group(1)
            else:
                subreddit = None
            articles.append(
                LatestArticle(
                    provider=self.name,
                    title=str(entry.get("title") or ""),
                    url=url,
                    description=_strip_html(body_html),
                    published_at=published_at,
                    source_name=f"r/{subreddit}" if subreddit else None,
                    language=language,
                    source_url=url,
                )
            )

        _search_cache[cache_key] = (time.monotonic(), list(articles))
        return articles
