"""RSS 수집 + Jina Reader 정제 + 중복 제거.

키워드로 Google News RSS 검색 피드를 조회해 최신 기사 URL을 모으고, 정규화한 URL과
제목으로 중복을 제거한 뒤, 상위 항목은 Jina Reader(r.jina.ai)로 본문을 정제해
짧은 요지를 만든다. 네트워크 경계 함수(피드 조회, Jina 조회)를 분리해 테스트에서
대체할 수 있게 한다.
"""

from __future__ import annotations

from urllib.parse import quote_plus, urlsplit, urlunsplit

# Jina Reader 조회 타임아웃(초)과 요지로 사용할 최대 문자 수.
_JINA_TIMEOUT = 12.0
_SNIPPET_CHARS = 280


def build_news_feed_url(keyword: str, language: str = "ko", country: str = "KR") -> str:
    """키워드로 Google News RSS 검색 피드 URL을 만든다."""
    query = quote_plus(keyword)
    ceid = f"{country}:{language}"
    return (
        f"https://news.google.com/rss/search?q={query}"
        f"&hl={language}&gl={country}&ceid={ceid}"
    )


def canonical_url(url: str) -> str:
    """추적 파라미터와 fragment를 제거해 중복 판별용 정규 URL을 만든다."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    # query와 fragment는 중복 판별에서 무시한다.
    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), "", ""))


def fetch_feed_entries(feed_url: str) -> list[dict[str, object]]:
    """RSS 피드를 파싱해 항목 목록을 반환한다.

    Returns:
        {title, link, summary, published, published_ts} 딕셔너리 리스트
        (published_ts는 정렬용 정수 타임스탬프, 없으면 0)
    """
    import calendar

    import feedparser

    parsed = feedparser.parse(feed_url)
    entries: list[dict[str, object]] = []
    for entry in parsed.entries:
        published_struct = entry.get("published_parsed")
        published_ts = calendar.timegm(published_struct) if published_struct else 0
        entries.append(
            {
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", ""),
                "published": entry.get("published", ""),
                "published_ts": published_ts,
            }
        )
    return entries


def deduplicate(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    """정규 URL과 정규화한 제목 기준으로 중복 항목을 제거한다.

    최신순으로 정렬한 뒤 앞선(더 최신) 항목을 남긴다.
    """
    ordered = sorted(entries, key=lambda item: item.get("published_ts", 0), reverse=True)
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[dict[str, object]] = []
    for entry in ordered:
        url_key = canonical_url(str(entry.get("link", "")))
        title_key = " ".join(str(entry.get("title", "")).lower().split())
        if url_key in seen_urls or (title_key and title_key in seen_titles):
            continue
        seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        unique.append(entry)
    return unique


def jina_read(url: str) -> str | None:
    """Jina Reader로 URL 본문을 정제한 텍스트를 가져온다. 실패 시 None."""
    import httpx

    try:
        response = httpx.get(f"https://r.jina.ai/{url}", timeout=_JINA_TIMEOUT)
        response.raise_for_status()
    except Exception:
        return None
    return response.text


def _make_snippet(entry: dict[str, object], use_jina: bool) -> str:
    """Jina 본문(가능하면) 또는 RSS 요약에서 짧은 요지를 만든다."""
    content = jina_read(str(entry.get("link", ""))) if use_jina else None
    source_text = content or str(entry.get("summary", ""))
    # RSS summary에는 HTML 태그가 섞일 수 있어 대략 제거한다.
    import re

    text = re.sub(r"<[^>]+>", "", source_text)
    text = " ".join(text.split())
    return text[:_SNIPPET_CHARS]


def latest_articles(
    keyword: str, limit: int = 6, jina_top: int = 4
) -> list[dict[str, object]]:
    """키워드로 최신·중복 제거된 기사 URL 목록을 반환한다.

    Args:
        keyword: 검색어
        limit: 반환할 최대 기사 수
        jina_top: 상위 몇 개까지 Jina Reader로 본문 요지를 만들지

    Returns:
        {title, url, published, snippet} 딕셔너리 리스트
    """
    entries = fetch_feed_entries(build_news_feed_url(keyword))
    unique = deduplicate(entries)[:limit]

    articles: list[dict[str, object]] = []
    for index, entry in enumerate(unique):
        articles.append(
            {
                "title": entry.get("title"),
                "url": entry.get("link"),
                "published": entry.get("published"),
                "snippet": _make_snippet(entry, use_jina=index < jina_top),
            }
        )
    return articles
