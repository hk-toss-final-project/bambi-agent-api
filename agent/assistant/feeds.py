"""RSS 수집 + Jina Reader 정제 + 중복 제거.

키워드로 Google News RSS 검색 피드를 조회해 최신 기사 URL을 모으고, 정규화한 URL과
제목으로 중복을 제거한 뒤, 상위 항목은 Jina Reader(r.jina.ai)로 본문을 정제해
짧은 요지를 만든다. 네트워크 경계 함수(피드 조회, Jina 조회)를 분리해 테스트에서
대체할 수 있게 한다.

RSS는 YouTube와 달리 정확한 발행 시각(published_parsed)을 제공하므로, "어제 날짜"를
근사가 아니라 달력상 정확한 하루로 판별할 수 있다. 뉴스 검색이 한국어(hl=ko, gl=KR)
기준이므로 판별 기준 시간대는 한국 시간(Asia/Seoul)으로 고정한다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote_plus, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

# Jina Reader 조회 타임아웃(초)과 요지로 사용할 최대 문자 수.
_JINA_TIMEOUT = 12.0
_SNIPPET_CHARS = 280

# "어제 기사" 판별 기준 시간대.
_ARTICLE_TIMEZONE = ZoneInfo("Asia/Seoul")


def build_news_feed_url(
    keyword: str,
    language: str = "ko",
    country: str = "KR",
    *,
    after: date | None = None,
    before: date | None = None,
) -> str:
    """키워드로 Google News RSS 검색 피드 URL을 만든다.

    after/before를 주면 Google News의 날짜 검색 연산자(after:/before:)를 쿼리에
    붙여 서버 단에서부터 기간을 좁힌다. 검색 결과는 최대 약 100건으로 제한되므로,
    이렇게 기간을 좁혀야 특정 날짜(예: 어제)의 기사가 오늘 발행된 기사에 밀려
    아예 빠지는 상황을 막을 수 있다. 다만 Google이 이 연산자를 완벽히 정확하게
    지키지는 않으므로, 정확한 판별은 여전히 클라이언트 측 filter_to_date로 한다.
    """
    date_filters = ""
    if after is not None:
        date_filters += f" after:{after.isoformat()}"
    if before is not None:
        date_filters += f" before:{before.isoformat()}"
    query = quote_plus(f"{keyword}{date_filters}")
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


def _published_date(published_ts: int):
    """published_ts(UTC 초 단위 타임스탬프)를 판별 기준 시간대의 날짜로 변환한다.

    타임스탬프를 알 수 없으면(0) None을 반환한다.
    """
    if not published_ts:
        return None
    return datetime.fromtimestamp(published_ts, tz=UTC).astimezone(_ARTICLE_TIMEZONE).date()


def filter_to_date(entries: list[dict[str, object]], target_date) -> list[dict[str, object]]:
    """발행일이 지정한 날짜와 정확히 일치하는 항목만 남긴다.

    발행 시각을 알 수 없는 항목은 그 날짜인지 확신할 수 없으므로 제외한다.
    """
    return [entry for entry in entries if _published_date(entry.get("published_ts", 0)) == target_date]


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
    keyword: str,
    limit: int = 6,
    jina_top: int = 4,
    *,
    yesterday_only: bool = True,
    reference_now: datetime | None = None,
) -> list[dict[str, object]]:
    """키워드로 어제 날짜 기사만(기본값) 중복 제거해 반환한다.

    Args:
        keyword: 검색어
        limit: 반환할 최대 기사 수
        jina_top: 상위 몇 개까지 Jina Reader로 본문 요지를 만들지
        yesterday_only: True면 한국 시간 기준 어제 발행된 기사만 남긴다.
            발행 시각을 알 수 없는 기사는 이 필터에서 제외된다.
        reference_now: "지금" 기준 시각(테스트용). 생략하면 실제 현재 시각을 쓴다.

    Returns:
        {title, url, published, snippet} 딕셔너리 리스트
    """
    if yesterday_only:
        now = reference_now or datetime.now(_ARTICLE_TIMEZONE)
        yesterday = (now.astimezone(_ARTICLE_TIMEZONE) - timedelta(days=1)).date()
        # 서버 단에서부터 기간을 좁혀, 인기 검색어에서 오늘 기사에 밀려 어제
        # 기사가 검색 결과(최대 약 100건)에서 아예 빠지는 상황을 줄인다.
        feed_url = build_news_feed_url(keyword, after=yesterday, before=yesterday + timedelta(days=1))
        entries = filter_to_date(fetch_feed_entries(feed_url), yesterday)
    else:
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
