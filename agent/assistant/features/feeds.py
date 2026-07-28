"""뉴스 Provider 수집 어댑터 + Jina Reader 정제 + 중복 제거.

키워드로 공용 뉴스 Provider(Naver·GDELT·Google News RSS — Global 수집과 같은
커넥터 계층)를 조회해 최신 기사를 모으고, 정규화한 URL과 제목으로 중복을
제거한 뒤, 상위 항목은 Jina Reader로 본문을 정제해 짧은 요지를 만든다.
네트워크 경계 함수(Provider 조회, Jina 조회)를 분리해 테스트에서 대체할 수
있게 한다.

리포트의 신선도는 최신성 컷으로 보장한다 — 발행된 지 일정 시간(기본 48시간)
이내인 기사만 후보로 삼는다. 이미 보고한 기사를 제외하다 보면 목록의 점점
아래쪽(옛날 기사)을 파고 내려가게 되는데, 이를 차단한다. (이전에는 "달력상
정확히 어제" 발행 기사만 남기는 필터를 썼으나, Google News가 최신순 최대 약
100건만 주기 때문에 기사가 많은 키워드에서는 어제 기사가 결과에서 밀려나 항상
0건이 되는 문제가 있었다.)
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from infrastructure.sources.connectors.api import (
        LatestArticle,
        LatestInformationProvider,
    )

logger = logging.getLogger("agent.assistant.features.feeds")

# Jina Reader 조회 타임아웃(초)과 요지로 사용할 최대 문자 수.
_JINA_TIMEOUT = 12.0
_SNIPPET_CHARS = 280

# "최근 기사" 판별 기준. 발행된 지 이 시간 이내인 기사만 리포트 후보로 삼는다.
# YouTube 쪽 근사 필터(youtube._DEFAULT_MAX_AGE_HOURS)와 같은 48시간을 기본값으로
# 두어 에이전트 전체의 "최근" 기준을 일관되게 유지한다.
_DEFAULT_MAX_AGE_HOURS = 48.0


def _build_default_providers() -> list["LatestInformationProvider"]:
    """환경 자격 증명에 맞춰 사용할 뉴스 Provider 목록을 만든다.

    Google News RSS는 키가 필요 없어 항상 포함하고, Naver는 자격 증명이
    있을 때만 넣는다(팀원 로컬처럼 키 없는 환경에서도 비서가 동작해야 한다).
    """
    import os

    from infrastructure.sources.connectors.api import (
        GdeltNewsProvider,
        GoogleNewsRssProvider,
        NaverNewsProvider,
    )

    providers: list[LatestInformationProvider] = [GoogleNewsRssProvider()]
    naver_id = os.getenv("NAVER_CLIENT_ID")
    naver_secret = os.getenv("NAVER_CLIENT_SECRET")
    if naver_id and naver_secret:
        providers.append(NaverNewsProvider(naver_id, naver_secret))
    providers.append(
        GdeltNewsProvider(os.getenv("GDELT_BASE_URL") or "https://api.gdeltproject.org")
    )
    return providers


def _article_to_entry(article: "LatestArticle") -> dict[str, object]:
    """Provider 공통 기사 모델을 파이프라인이 쓰는 entry 딕셔너리로 변환한다."""
    published_at = article.published_at
    if published_at is not None and published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    return {
        "title": article.title,
        "link": article.url,
        "summary": article.description,
        "published": published_at.isoformat() if published_at else "",
        "published_ts": int(published_at.timestamp()) if published_at else 0,
        "source_url": article.source_url or "",
        "source_name": article.source_name or "",
    }


def fetch_provider_entries(
    keyword: str,
    *,
    limit_per_provider: int = 15,
    providers: Sequence["LatestInformationProvider"] | None = None,
) -> list[dict[str, object]]:
    """공용 뉴스 Provider들에서 최신 기사를 모아 entry 목록으로 반환한다.

    Global 수집과 같은 Provider 계층을 사용해 두 파이프라인의 근거 풀이
    갈라지지 않게 한다. Provider 실패는 서로 격리한다 — 소스 하나가 죽어도
    비서 리포트는 나머지 소스로 계속된다.

    Args:
        keyword: 검색 키워드
        limit_per_provider: Provider당 최대 기사 수
        providers: 조회할 Provider 목록. 생략하면 환경 자격 증명 기준 기본 구성.

    Returns:
        {title, link, summary, published, published_ts, source_url, source_name}
        딕셔너리 리스트 (published_ts는 정렬용 정수 타임스탬프, 없으면 0)
    """
    import asyncio

    selected = list(providers) if providers is not None else _build_default_providers()
    if not selected:
        return []

    async def _search_all() -> list[object]:
        return await asyncio.gather(
            *(
                provider.search(
                    query=keyword, limit=limit_per_provider, language="ko"
                )
                for provider in selected
            ),
            return_exceptions=True,
        )

    entries: list[dict[str, object]] = []
    for provider, result in zip(selected, asyncio.run(_search_all()), strict=True):
        if isinstance(result, BaseException):
            logger.warning(
                "뉴스 Provider %s 조회 실패, 나머지 소스로 계속한다: %s",
                provider.name,
                result,
            )
            continue
        entries.extend(_article_to_entry(article) for article in result)
    return entries


def canonical_url(url: str) -> str:
    """추적 파라미터와 fragment를 제거해 중복 판별용 정규 URL을 만든다."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    # query와 fragment는 중복 판별에서 무시한다.
    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), "", ""))


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
    """Jina Reader로 URL 본문을 정제한 텍스트를 가져온다. 실패 시 None.

    호출은 공유 Jina 커넥터에 위임한다(인증·오류 처리 일원화). 비서는 기사
    하나쯤 실패해도 리포트를 계속 만들어야 하므로 예외 대신 None을 준다.
    'Image N:' 헤더로 대표 이미지를 뽑아야 해서 원문 전체를 받는다.
    """
    from infrastructure.sources.connectors.api import (
        JinaReadError,
        fetch_url_raw_via_jina,
    )

    try:
        return fetch_url_raw_via_jina(url, timeout=_JINA_TIMEOUT)
    except JinaReadError:
        return None


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


def article_body_offset(markdown: str, title: str) -> int:
    """원문에서 기사 본문이 시작하는 위치를 찾는다. 못 찾으면 0.

    Jina Reader는 페이지 전체를 Markdown으로 옮기므로 앞부분이 사이트 메뉴·배너다.
    앞에서부터 자르면 메뉴만 담기는 매체가 있다(2026-07-28 실측: 톱스타뉴스는
    본문 전 7,221자, 뉴스투데이는 24,169자가 메뉴였다).

    내비게이션은 기사 제목을 담지 않지만 본문 머리에는 제목이 그대로 나온다.
    그 지점을 본문 시작으로 본다.

    제목을 그대로 찾으면 실패한다(실측 1/8) — DB 제목과 원문의 따옴표·말줄임표
    표기가 다르기 때문이다. 글자만 뽑아 사이에 기호가 끼어드는 것을 허용하는
    패턴으로 찾으면 12/12로 맞았다.

    Args:
        markdown: Jina Reader 원문
        title: 수집 시 저장한 기사 제목

    Returns:
        본문 시작 위치(문자 인덱스). 제목을 찾지 못하면 0.
    """
    import re

    letters = re.findall(r"[0-9A-Za-z가-힣]", title)[:12]
    # 글자가 너무 적으면 우연히 메뉴에 걸릴 수 있어 시도하지 않는다.
    if len(letters) < 6:
        return 0
    pattern = r"[^0-9A-Za-z가-힣]{0,4}".join(re.escape(c) for c in letters)
    match = re.search(pattern, markdown)
    return match.start() if match else 0


def clean_article_body(markdown: str, max_chars: int = 2000, *, title: str = "") -> str:
    """저장된 기사 본문 Markdown을 파이프라인 입력 텍스트로 정제한다.

    Global 저장소에서 재사용한 본문(마크다운)을 임베딩·통합 요약에 넣을 수
    있게 표기를 걷어내고 공백을 정리한다. 상한은 임베딩 입력 상한(2000자)에
    맞춘다.

    title을 주면 메뉴 구간을 건너뛰고 본문부터 자른다(article_body_offset 참고).
    주지 않으면 기존대로 처음부터 자른다 — 호출부를 깨지 않기 위한 기본값이다.
    """
    if title:
        offset = article_body_offset(markdown, title)
        if offset:
            markdown = markdown[offset:]
    text = _clean_jina_content(markdown)
    return " ".join(text.split())[:max_chars]


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
    from agent.assistant.features.summarize import summarize_text

    return summarize_text(
        content,
        instruction=(
            f"다음은 '{title}' 뉴스 기사 페이지에서 추출한 텍스트다. "
            "메뉴·네비게이션·광고·언론사 이름 같은 잡음은 무시하고, "
            "기사 핵심 내용만 한국어 한두 문장으로 요약하라."
        ),
        model=model,
    )
