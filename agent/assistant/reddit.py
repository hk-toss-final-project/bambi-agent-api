"""Reddit 검색과 게시글 요약.

Reddit의 비공식 JSON API(`search.json`, `<permalink>.json`)는 브라우저가 아닌 요청을
상시 차단해 사용할 수 없다. 대신 공개 RSS 피드(`search.rss`)는 정상 접근 가능해
feedparser로 파싱한다. RSS는 비공식 JSON API보다 얻을 수 있는 정보가 적어(점수,
댓글 수 없음, 댓글 본문도 안정적으로 제공되지 않음) 게시글 제목과 본문(또는 외부
링크 설명) 중심으로 요약한다.

RSS도 짧은 시간에 반복 요청하면 429(rate limit)가 발생하므로 요청 사이에 지연을
둔다.
"""

from __future__ import annotations

import re
import time
from urllib.parse import quote_plus

from agent.assistant.summarize import summarize_text

_SEARCH_RSS_URL = "https://www.reddit.com/search.rss"
# Reddit이 User-Agent 없는 요청을 더 쉽게 차단/제한하므로 고유 User-Agent를 명시한다.
_HEADERS = {"User-Agent": "bambi-keyword-assistant/0.1 (keyword digest)"}
# 게시글 사이 요청 지연(초). 반복 요청으로 인한 429 재발을 막기 위한 완화책이다.
_REQUEST_DELAY_SECONDS = 2.0
_SUBREDDIT_PATTERN = re.compile(r"to\s*<a[^>]*>\s*r/([^\s<]+)")
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """HTML 태그를 제거하고 공백을 정리한다."""
    return " ".join(_HTML_TAG_PATTERN.sub(" ", text).split())


def search_posts(keyword: str, limit: int = 4) -> list[dict[str, object]]:
    """키워드로 Reddit 게시글을 검색해 메타데이터 목록을 반환한다.

    Args:
        keyword: 검색어
        limit: 가져올 게시글 수

    Returns:
        {id, title, url, subreddit, body} 딕셔너리 리스트
    """
    import feedparser

    query = quote_plus(keyword)
    feed_url = f"{_SEARCH_RSS_URL}?q={query}&limit={limit}&sort=relevance"
    parsed = feedparser.parse(feed_url, request_headers=_HEADERS)

    status = parsed.get("status")
    if status is not None and status >= 400:
        raise RuntimeError(f"Reddit search.rss 요청 실패 (status={status}). 잠시 후 다시 시도하세요.")

    posts: list[dict[str, object]] = []
    for entry in parsed.entries[:limit]:
        summary_html = str(entry.get("summary", ""))
        subreddit_match = _SUBREDDIT_PATTERN.search(summary_html)
        content = entry.get("content")
        body_html = str(content[0].get("value", "")) if content else summary_html

        posts.append(
            {
                "id": entry.get("id"),
                "title": entry.get("title"),
                "url": entry.get("link"),
                "subreddit": subreddit_match.group(1) if subreddit_match else None,
                "body": _strip_html(body_html),
            }
        )
    return posts


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
        "summary": summary,
        "note": note,
    }


def reddit_digest(keyword: str, limit: int = 4, model: str = "gpt-4.1-mini") -> list[dict[str, object]]:
    """키워드로 게시글을 검색하고, 요청 사이 지연을 두며 각 게시글을 요약한다."""
    posts = search_posts(keyword, limit=limit)

    results: list[dict[str, object]] = []
    for index, post in enumerate(posts):
        if index > 0:
            time.sleep(_REQUEST_DELAY_SECONDS)
        results.append(summarize_post(post, model=model))
    return results
