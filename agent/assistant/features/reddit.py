"""Reddit 검색과 게시글 요약.

Reddit의 비공식 JSON API(`search.json`, `<permalink>.json`)는 브라우저가 아닌 요청을
상시 차단해 사용할 수 없다. 대신 공개 RSS 피드(`search.rss`)는 정상 접근 가능해
feedparser로 파싱한다. RSS는 비공식 JSON API보다 얻을 수 있는 정보가 적어(점수,
댓글 수 없음, 댓글 본문도 안정적으로 제공되지 않음) 게시글 제목과 본문(또는 외부
링크 설명) 중심으로 요약한다.

Reddit의 RSS는 비인증 요청에 매우 빡빡한 레이트리밋을 건다(요청 1번이면
`x-ratelimit-remaining`이 곧바로 0이 되고, 수십 초 뒤에야 리셋된다). 이를 다루기
위해 두 가지를 둔다:

1. 429를 받으면 응답의 `x-ratelimit-reset`(초)만큼 기다렸다가 한 번 재시도한다.
2. 같은 키워드 검색 결과를 짧은 시간(캐시 TTL) 재사용해, 반복 검색이 매번 새
   요청을 만들지 않게 한다.

재시도까지 실패하면 예외를 그대로 던진다 — 실패를 "결과 없음"으로 조용히 숨기지
않는다.
"""

from __future__ import annotations

import calendar
import re
import time
from datetime import datetime
from urllib.parse import quote_plus

from agent.assistant.features import feeds
from agent.assistant.features.summarize import summarize_text

_SEARCH_RSS_URL = "https://www.reddit.com/search.rss"
# Reddit이 User-Agent 없는 요청을 더 쉽게 차단/제한하므로 고유 User-Agent를 명시한다.
_HEADERS = {"User-Agent": "report-builder-keyword-assistant/0.1 (keyword digest)"}

# 429 응답을 받았을 때 재시도 전 대기 시간. x-ratelimit-reset 헤더가 있으면 그
# 값을 쓰고, 없으면 기본값을 쓴다. 사용자 요청이 너무 오래 걸리지 않도록 상한을 둔다.
_DEFAULT_RETRY_WAIT_SECONDS = 5.0
_MAX_RETRY_WAIT_SECONDS = 30.0

# 같은 키워드 검색 결과를 재사용하는 시간(초). Reddit의 레이트리밋 리셋 주기보다
# 넉넉히 길게 잡아, 재검색이 새 요청을 만들지 않게 한다.
_CACHE_TTL_SECONDS = 90.0
_search_cache: dict[str, tuple[float, list[dict[str, object]]]] = {}

_SUBREDDIT_PATTERN = re.compile(r"to\s*<a[^>]*>\s*r/([^\s<]+)")
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """HTML 태그를 제거하고 공백을 정리한다."""
    return " ".join(_HTML_TAG_PATTERN.sub(" ", text).split())


def _cache_key(keyword: str, limit: int, filter_tag: str) -> str:
    """키워드를 대소문자·공백 차이 없이 캐시 조회할 수 있게 정규화한다."""
    return f"{' '.join(keyword.strip().lower().split())}::{limit}::{filter_tag}"


def _parse_posts(entries, limit: int) -> list[dict[str, object]]:
    """feedparser 엔트리 목록을 게시글 딕셔너리 목록으로 변환한다."""
    posts: list[dict[str, object]] = []
    for entry in entries[:limit]:
        summary_html = str(entry.get("summary", ""))
        subreddit_match = _SUBREDDIT_PATTERN.search(summary_html)
        content = entry.get("content")
        body_html = str(content[0].get("value", "")) if content else summary_html
        published_struct = entry.get("published_parsed")
        published_ts = calendar.timegm(published_struct) if published_struct else 0

        posts.append(
            {
                "id": entry.get("id"),
                "title": entry.get("title"),
                "url": entry.get("link"),
                "subreddit": subreddit_match.group(1) if subreddit_match else None,
                "body": _strip_html(body_html),
                "published": entry.get("published", ""),
                "published_ts": published_ts,
            }
        )
    return posts


def _fetch_feed(feed_url: str):
    """RSS 피드를 조회한다. 429를 받으면 리셋 시간만큼 기다린 뒤 한 번 재시도한다."""
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
        raise RuntimeError(
            f"Reddit search.rss 요청 실패 (status={status}). 잠시 후 다시 시도하세요."
        )
    return parsed


def _search_articles(keyword: str, limit: int):
    """공용 Reddit 커넥터로 검색한다 (네트워크 경계, 테스트에서 대체 가능).

    최신순(sort=new)을 명시한다. 이 경로는 받아온 게시글을 다시 48시간 이내로
    거르므로(search_posts), 점수순으로 받으면 기간 안의 새 글이 아예 목록에
    들어오지 못해 결과가 비어 버린다. 점수순은 Global 수집 경로의 기본값이다.
    """
    import asyncio

    from infrastructure.sources.connectors.api import RedditSearchProvider

    return asyncio.run(
        RedditSearchProvider(sort="new").search(
            query=keyword, limit=limit, language=None
        )
    )


def _articles_to_posts(articles) -> list[dict[str, object]]:
    """공용 최신 문서를 비서 파이프라인이 쓰는 게시글 딕셔너리로 변환한다."""
    posts: list[dict[str, object]] = []
    for article in articles:
        published_at = article.published_at
        source_name = str(article.source_name or "")
        posts.append(
            {
                "id": article.url,
                "title": article.title,
                "url": article.url,
                # Provider는 "r/이름" 형태로 주므로 접두사를 떼어 기존 계약을 지킨다.
                "subreddit": source_name.removeprefix("r/") or None,
                "body": article.description,
                "published": published_at.isoformat() if published_at else "",
                "published_ts": int(published_at.timestamp()) if published_at else 0,
            }
        )
    return posts


def search_posts(
    keyword: str,
    limit: int = 4,
    *,
    max_age_hours: float = feeds._DEFAULT_MAX_AGE_HOURS,
    reference_now: datetime | None = None,
) -> list[dict[str, object]]:
    """키워드로 최근 작성된 Reddit 게시글을 검색해 메타데이터 목록을 반환한다.

    뉴스 기사와 같은 기준(발행된 지 max_age_hours 이내, 기본 48시간)으로 최근
    게시글만 남긴다. 발행 시각이 없는 항목(서브레딧 추천 등)은 제외한다. 최근
    게시글을 놓치지 않도록 최신순(sort=new)으로 넉넉한 풀을 받아와 클라이언트에서
    경과 시간으로 거른다. 짧은 시간 내 같은 검색은 캐시된 결과를 그대로 반환한다.
    조건을 만족하는 게시글이 없으면 빈 리스트를 반환한다(새 소식 없음).

    Args:
        keyword: 검색어
        limit: 가져올 게시글 수
        max_age_hours: 작성 경과 시간 허용 상한(시간). 이보다 오래된 게시글은 제외한다.
        reference_now: "지금" 기준 시각(테스트용). 생략하면 실제 현재 시각을 쓴다.

    Returns:
        {id, title, url, subreddit, body, published, published_ts} 딕셔너리 리스트

    검색 자체는 공용 수집 커넥터(RedditSearchProvider)에 위임한다 — Global 수집
    워커와 같은 코드를 써서 수집 경로가 갈라지지 않게 한다(레이트리밋 재시도·캐시도
    Provider가 갖고 있다). 여기서는 최근성 필터와 비서 파이프라인이 기대하는
    딕셔너리 모양만 담당한다.
    """
    # 경과 시간으로 걸러내면 대부분 탈락하므로 피드가 주는 최대치(약 25건)를 받아온다.
    fetch_limit = 25

    cache_key = _cache_key(keyword, limit, f"recent:{max_age_hours}")
    cached = _search_cache.get(cache_key)
    if cached is not None and cached[0] > time.time():
        return list(cached[1])

    posts = _articles_to_posts(_search_articles(keyword, fetch_limit))
    posts = feeds.filter_recent_entries(posts, max_age_hours=max_age_hours, reference_now=reference_now)
    posts = posts[:limit]

    _search_cache[cache_key] = (time.time() + _CACHE_TTL_SECONDS, posts)
    return list(posts)


def summarize_post(post: dict[str, object], model: str = "gpt-4.1-mini") -> dict[str, object]:
    """게시글 하나의 제목·본문을 요약해 결과 딕셔너리를 만든다.

    본문이 없으면(외부 링크만 있는 짧은 글 등) 안내 문구를 넣는다.
    """
    body = str(post.get("body") or "").strip()

    if body:
        summary = summarize_text(
            body,
            instruction=f"다음 Reddit 게시글 '{post.get('title')}'의 내용을 요약해줘.",
            model=model,
        )
        note = None
    else:
        summary = None
        note = "본문이 없어 요약할 수 없습니다."

    return {
        "title": post.get("title"),
        "url": post.get("url"),
        "subreddit": post.get("subreddit"),
        "published": post.get("published"),
        "summary": summary,
        "note": note,
    }
