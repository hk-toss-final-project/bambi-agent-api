"""RSS 수집 + Jina Reader 정제 + 중복 제거.

키워드로 Google News RSS 검색 피드를 조회해 최신 기사 URL을 모으고, 정규화한 URL과
제목으로 중복을 제거한 뒤, 상위 항목은 Jina Reader(r.jina.ai)로 본문을 정제해
짧은 요지를 만든다. 네트워크 경계 함수(피드 조회, Jina 조회)를 분리해 테스트에서
대체할 수 있게 한다.

리포트의 신선도는 두 필터의 조합으로 보장한다:

1. 최신성 컷 — 발행된 지 일정 시간(기본 48시간) 이내인 기사만 후보로 삼는다.
   이미 보고한 기사를 제외하다 보면 목록의 점점 아래쪽(옛날 기사)을 파고
   내려가게 되는데, 이를 차단한다.
2. 보고 이력 제외 — 호출자가 넘긴 "이미 보고한 기사의 정규 URL"에 있는 기사는
   제외한다. 갱신이 느린 키워드에서 매번 같은 보고서가 반복되는 것을 막는다.

새 기사가 없으면 빈 리스트를 반환하며, 이는 오류가 아니라 "새로운 소식 없음"이라는
정상 결과다. (이전에는 "달력상 정확히 어제" 발행 기사만 남기는 필터를 썼으나,
Google News가 최신순 최대 약 100건만 주기 때문에 기사가 많은 키워드에서는 어제
기사가 결과에서 밀려나 항상 0건이 되는 문제가 있었다.)
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote_plus, urlsplit, urlunsplit

# Jina Reader 조회 타임아웃(초)과 요지로 사용할 최대 문자 수.
_JINA_TIMEOUT = 12.0
_SNIPPET_CHARS = 280

# "최근 기사" 판별 기준. 발행된 지 이 시간 이내인 기사만 리포트 후보로 삼는다.
# YouTube 쪽 근사 필터(youtube._DEFAULT_MAX_AGE_HOURS)와 같은 48시간을 기본값으로
# 두어 에이전트 전체의 "최근" 기준을 일관되게 유지한다.
_DEFAULT_MAX_AGE_HOURS = 48.0


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


def filter_recent_entries(
    entries: list[dict[str, object]],
    max_age_hours: float = _DEFAULT_MAX_AGE_HOURS,
    reference_now: datetime | None = None,
) -> list[dict[str, object]]:
    """발행된 지 기준 시간 이내인 항목만 남긴다.

    발행 시각을 알 수 없는(published_ts가 0인) 항목은 최근 여부를 확신할 수 없으므로
    제외한다. reference_now는 테스트에서 "지금"을 고정하기 위한 파라미터다.
    """
    now = reference_now or datetime.now(UTC)
    cutoff_ts = now.timestamp() - max_age_hours * 3600
    return [
        entry
        for entry in entries
        if entry.get("published_ts", 0) and int(entry["published_ts"]) >= cutoff_ts
    ]


def jina_read(url: str) -> str | None:
    """Jina Reader로 URL 본문을 정제한 텍스트를 가져온다. 실패 시 None."""
    import httpx

    try:
        response = httpx.get(f"https://r.jina.ai/{url}", timeout=_JINA_TIMEOUT)
        response.raise_for_status()
    except Exception:
        return None
    return response.text


def _clean_jina_content(text: str) -> str:
    """Jina Reader 응답에서 메타데이터 헤더와 마크다운 표기를 제거해 본문만 남긴다.

    Jina 응답은 'Title: ...', 'URL Source: ...', 'Published Time: ...',
    'Markdown Content:' 헤더로 시작한다. 이 헤더 블록을 걷어내고, 링크·이미지
    같은 마크다운 표기도 사람이 읽는 텍스트만 남긴다.
    """
    import re

    marker = "Markdown Content:"
    if marker in text:
        text = text.split(marker, 1)[1]
    else:
        # 헤더만 있고 마커가 잘린 경우, 알려진 헤더 줄들을 개별 제거한다.
        text = re.sub(r"^(Title|URL Source|Published Time|Image \d+):.*$", "", text, flags=re.MULTILINE)

    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)        # 이미지
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)     # 링크 → 텍스트만
    text = re.sub(r"[#>*`_~-]+", " ", text)                    # 마크다운 기호
    text = re.sub(r"https?://\S+", " ", text)                  # 남은 raw URL
    return text


def _extract_jina_image(text: str) -> str | None:
    """Jina 응답에서 기사 대표 이미지 URL을 하나 뽑는다. 없으면 None.

    Jina는 헤더에 'Image N: <url>' 형태로, 본문에는 마크다운 이미지 '![alt](url)'
    형태로 이미지를 남긴다. 아이콘·로고·트래킹 픽셀 등은 대표 이미지가 아니므로
    최소 폭을 가진 흔한 이미지 확장자를 우선한다.
    """
    import re

    candidates = re.findall(r"Image \d+:\s*(https?://\S+)", text)
    candidates += re.findall(r"!\[[^\]]*\]\((https?://[^)]+)\)", text)
    for url in candidates:
        low = url.lower()
        if any(bad in low for bad in ("logo", "icon", "sprite", "1x1", "blank", "avatar")):
            continue
        if re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", low):
            return url
    return candidates[0] if candidates else None


def _clean_text(entry: dict[str, object], content: str | None, max_chars: int) -> str:
    """Jina 콘텐츠(있으면) 또는 RSS 요약을 정제해 사람이 읽는 텍스트로 만든다."""
    import html as html_lib
    import re

    if content:
        text = _clean_jina_content(content)
    else:
        text = re.sub(r"<[^>]+>", " ", str(entry.get("summary", "")))
        text = re.sub(r"https?://\S+", " ", text)
    text = html_lib.unescape(text)
    return " ".join(text.split())[:max_chars]


def _make_snippet(entry: dict[str, object], content: str | None) -> str:
    """정제한 짧은 요지를 만든다. content는 미리 조회한 Jina 텍스트(없으면 None)."""
    return _clean_text(entry, content, _SNIPPET_CHARS)


def _article_full_text(entry: dict[str, object], content: str | None) -> str:
    """LLM 요약 입력용으로 기사 본문 텍스트를 넉넉히 확보한다(요지보다 길게)."""
    return _clean_text(entry, content, 4000)


def _summarize_article(title: str, content: str, model: str) -> str:
    """기사 본문을 메뉴·광고를 무시하고 한 문장으로 요약한다."""
    from agent.assistant.summarize import summarize_text

    return summarize_text(
        content,
        instruction=(
            f"다음은 '{title}' 뉴스 기사 페이지에서 추출한 텍스트다. "
            "메뉴·네비게이션·광고·언론사 이름 같은 잡음은 무시하고, "
            "기사 핵심 내용만 한국어 한두 문장으로 요약하라."
        ),
        model=model,
    )


def latest_articles(
    keyword: str,
    limit: int = 6,
    jina_top: int = 4,
    *,
    summarize: bool = False,
    model: str = "gpt-4.1-mini",
    max_age_hours: float = _DEFAULT_MAX_AGE_HOURS,
    exclude_urls: set[str] | None = None,
    reference_now: datetime | None = None,
) -> list[dict[str, object]]:
    """키워드로 최근 발행된 새 기사만 중복 제거해 반환한다.

    최신순 피드에서 발행 경과 시간이 max_age_hours 이내인 기사만 남기고,
    exclude_urls(이미 리포트에 실은 기사의 정규 URL)에 있는 기사는 제외한다.
    조건을 만족하는 새 기사가 없으면 빈 리스트를 반환하며, 이는 "새로운 소식
    없음"이라는 정상 결과다.

    Args:
        keyword: 검색어
        limit: 반환할 최대 기사 수
        jina_top: 상위 몇 개까지 Jina Reader로 본문 요지를 만들지
        max_age_hours: 발행 경과 시간 허용 상한(시간). 이보다 오래된 기사는 제외한다.
        exclude_urls: 제외할 기사의 정규 URL(canonical_url 결과) 집합.
        reference_now: "지금" 기준 시각(테스트용). 생략하면 실제 현재 시각을 쓴다.

    Returns:
        {title, url, published, snippet} 딕셔너리 리스트
    """
    entries = fetch_feed_entries(build_news_feed_url(keyword))
    recent = filter_recent_entries(entries, max_age_hours=max_age_hours, reference_now=reference_now)
    unique = deduplicate(recent)
    if exclude_urls:
        unique = [
            entry for entry in unique
            if canonical_url(str(entry.get("link", ""))) not in exclude_urls
        ]
    unique = unique[:limit]

    articles: list[dict[str, object]] = []
    for index, entry in enumerate(unique):
        # 상위 jina_top개만 Jina로 본문을 한 번 조회해, 요지·이미지에 함께 쓴다.
        content = jina_read(str(entry.get("link", ""))) if index < jina_top else None
        image_url = _extract_jina_image(content) if content else None
        if summarize:
            full_text = _article_full_text(entry, content)
            snippet = _summarize_article(str(entry.get("title") or ""), full_text, model) if full_text else ""
        else:
            snippet = _make_snippet(entry, content)
        articles.append(
            {
                "title": entry.get("title"),
                "url": entry.get("link"),
                "published": entry.get("published"),
                "snippet": snippet,
                "image_url": image_url,
            }
        )
    return articles
