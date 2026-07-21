"""문서 발행일 추출 (우선순위 폴백 체인).

각 문서의 발행일을 아래 우선순위로 추출한다:

1. RSS/API의 pubDate (published_ts)
2. HTML 메타태그 — `article:published_time`, JSON-LD `datePublished`
   (Jina Reader 텍스트의 `Published Time:` 헤더도 같은 단계로 취급)
3. URL 경로 패턴 — `/2026/07/`, `/2026/07/19/`, `20260719` 등
4. 본문 날짜 파싱 — htmldate 라이브러리 활용
5. 전부 실패 → None 반환. 호출자가 first_seen(최초 발견일)을 대용으로 쓴다.

어떤 단계에서 추출됐는지(method)를 함께 반환해, 파이프라인 로그로 남겨
나중에 추출 품질을 점검할 수 있게 한다.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

# URL 경로에서 날짜를 찾는 패턴들. (연, 월[, 일]) 그룹을 뽑는다.
_URL_DATE_PATTERNS = (
    re.compile(r"/(20\d{2})[/-](\d{1,2})[/-](\d{1,2})(?:/|$)"),  # /2026/07/19/
    re.compile(r"/(20\d{2})[/-](\d{1,2})(?:/|$)"),               # /2026/07/
    re.compile(r"(?:/|[-_=])(20\d{2})(\d{2})(\d{2})(?:\D|$)"),   # 20260719
)

_META_PATTERNS = (
    # <meta property="article:published_time" content="...">  (속성 순서 무관)
    re.compile(
        r"<meta[^>]+(?:property|name)=[\"']article:published_time[\"'][^>]*"
        r"content=[\"']([^\"']+)[\"']",
        re.IGNORECASE,
    ),
    re.compile(
        r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]*"
        r"(?:property|name)=[\"']article:published_time[\"']",
        re.IGNORECASE,
    ),
)

# Jina Reader 응답 헤더의 발행 시각 줄.
_JINA_PUBLISHED_PATTERN = re.compile(r"^Published Time:\s*(.+)$", re.MULTILINE)


def _parse_datetime(text: str) -> datetime | None:
    """ISO 8601 계열 날짜 문자열을 UTC aware datetime으로 파싱한다. 실패 시 None."""
    cleaned = text.strip()
    if not cleaned:
        return None
    # "Z" 접미사는 fromisoformat이 못 읽는 파이썬 버전이 있어 치환한다.
    cleaned = cleaned.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        # "Mon, 14 Jul 2026 09:00:00 GMT" 같은 RFC 2822 형식도 시도한다.
        from email.utils import parsedate_to_datetime

        try:
            parsed = parsedate_to_datetime(cleaned)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _build_date(year: int, month: int, day: int = 1) -> datetime | None:
    """연·월·일 숫자로 UTC datetime을 만든다. 범위가 어긋나면 None."""
    try:
        return datetime(year, month, day, tzinfo=UTC)
    except ValueError:
        return None


def from_pub_ts(published_ts: int | float | None) -> datetime | None:
    """1순위: RSS/API pubDate 타임스탬프를 datetime으로 변환한다. 없으면 None."""
    if not published_ts:
        return None
    try:
        return datetime.fromtimestamp(float(published_ts), tz=UTC)
    except (ValueError, OSError, OverflowError):
        return None


def from_html_meta(html: str) -> datetime | None:
    """2순위: HTML 메타태그·JSON-LD·Jina 헤더에서 발행일을 찾는다. 없으면 None."""
    if not html:
        return None

    for pattern in _META_PATTERNS:
        match = pattern.search(html)
        if match:
            parsed = _parse_datetime(match.group(1))
            if parsed:
                return parsed

    # JSON-LD의 "datePublished": "..." — 스크립트 블록 전체를 파싱하지 않고
    # 키-값 패턴만 찾는다(중첩·배열 형태가 많아 완전 파싱은 과하다).
    match = re.search(r"[\"']datePublished[\"']\s*:\s*[\"']([^\"']+)[\"']", html)
    if match:
        parsed = _parse_datetime(match.group(1))
        if parsed:
            return parsed

    match = _JINA_PUBLISHED_PATTERN.search(html)
    if match:
        parsed = _parse_datetime(match.group(1))
        if parsed:
            return parsed

    return None


def from_url_path(url: str) -> datetime | None:
    """3순위: URL 경로의 날짜 패턴(/2026/07/ 등)에서 발행일을 추정한다. 없으면 None."""
    if not url:
        return None
    for pattern in _URL_DATE_PATTERNS:
        match = pattern.search(url)
        if not match:
            continue
        groups = match.groups()
        year, month = int(groups[0]), int(groups[1])
        day = int(groups[2]) if len(groups) > 2 and groups[2] else 1
        parsed = _build_date(year, month, day)
        if parsed:
            return parsed
    return None


def from_body(html: str, url: str = "") -> datetime | None:
    """4순위: htmldate로 본문에서 발행일을 파싱한다. 실패 시 None."""
    if not html:
        return None
    try:
        from htmldate import find_date

        found = find_date(html, url=url or None, outputformat="%Y-%m-%d")
    except Exception:
        return None
    if not found:
        return None
    return _parse_datetime(found)


def extract_published(
    *,
    published_ts: int | float | None = None,
    html: str = "",
    url: str = "",
) -> tuple[datetime | None, str]:
    """문서 발행일을 우선순위 폴백 체인으로 추출한다.

    Args:
        published_ts: RSS/API가 준 발행 타임스탬프 (없으면 0/None)
        html: 본문 HTML 또는 Jina Reader 텍스트 (없으면 빈 문자열)
        url: 문서 URL

    Returns:
        (발행일 datetime 또는 None, 추출 방법 문자열)
        방법: "pub_date" | "html_meta" | "url_path" | "body_parse" | "none"
        None이면 호출자가 first_seen을 발행일 대용으로 쓴다.
    """
    parsed = from_pub_ts(published_ts)
    if parsed:
        return parsed, "pub_date"

    parsed = from_html_meta(html)
    if parsed:
        return parsed, "html_meta"

    parsed = from_url_path(url)
    if parsed:
        return parsed, "url_path"

    parsed = from_body(html, url)
    if parsed:
        return parsed, "body_parse"

    return None, "none"
