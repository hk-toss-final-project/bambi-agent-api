"""YouTube 검색 Provider (공용 수집 커넥터).

키워드로 YouTube 영상을 검색해 공통 최신 문서(LatestArticle)로 정규화한다.
API Key 없이 youtube-search-python 스크래핑으로 동작한다.

이 모듈은 **검색(수집)** 단계만 담당한다. 자막 조회·요약은 소비 단계의 관심사라
비서(agent/assistant)에 남긴다 — 수집은 "무엇이 있는지"를 풀에 채우고, 본문
확보는 별도 fetcher 단계에서 하는 기존 수집 계층 규칙(뉴스 = 목록 수집 →
Jina 본문 확보)과 같은 분리다.

발행 시각 제약: youtube-search-python은 정확한 시각 대신 "19 hours ago",
"1일 전" 같은 상대 표현만 준다. 이를 근사 환산해 published_at을 만든다.
정확도가 필요한 소비자는 근사값임을 감안해야 한다.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from infrastructure.sources.connectors.features.latest import (
    LatestArticle,
    LatestProviderError,
)

# 상대 표현 단위를 시간으로 환산하는 표 (영문/국문).
_UNIT_HOURS = {
    "second": 1 / 3600,
    "minute": 1 / 60,
    "hour": 1.0,
    "day": 24.0,
    "week": 24.0 * 7,
    "month": 24.0 * 30,
    "year": 24.0 * 365,
}
_KO_UNIT_HOURS = {
    "초": 1 / 3600,
    "분": 1 / 60,
    "시간": 1.0,
    "일": 24.0,
    "주": 24.0 * 7,
    "개월": 24.0 * 30,
    "달": 24.0 * 30,
    "년": 24.0 * 365,
}

_EN_RELATIVE = re.compile(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago", re.I)
_EN_SINGULAR = re.compile(r"an?\s+(second|minute|hour|day|week|month|year)\s*ago", re.I)
_KO_RELATIVE = re.compile(r"(\d+)\s*(초|분|시간|일|주|개월|달|년)\s*전")


def relative_age_hours(published_time: str) -> float | None:
    """상대 발행 표현("19 hours ago", "3일 전")을 경과 시간(시간)으로 환산한다.

    Args:
        published_time: YouTube가 주는 상대 시간 문자열

    Returns:
        경과 시간(시간). 해석할 수 없으면 None.
    """
    text = str(published_time or "").strip()
    if not text:
        return None
    if match := _EN_RELATIVE.search(text):
        return int(match.group(1)) * _UNIT_HOURS[match.group(2).lower()]
    if match := _EN_SINGULAR.search(text):
        return _UNIT_HOURS[match.group(1).lower()]
    if match := _KO_RELATIVE.search(text):
        return int(match.group(1)) * _KO_UNIT_HOURS[match.group(2)]
    return None


def thumbnail_url(video_id: str) -> str | None:
    """video_id만으로 조립 가능한 공식 썸네일 URL을 만든다 (API 키 불필요)."""
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None


class YouTubeSearchProvider:
    """YouTube 검색 결과를 공통 최신 문서로 정규화한다.

    API Key가 필요 없어 자격 증명 없는 환경에서도 동작한다. 대신
    youtube-search-python 스크래핑에 의존하므로 YouTube 페이지 구조 변경에
    취약하고, httpx<0.28 핀이 이 라이브러리 때문에 필요하다.
    """

    name = "youtube"

    async def search(
        self, *, query: str, limit: int, language: str | None
    ) -> list[LatestArticle]:
        """키워드로 영상을 검색해 최신 문서 목록을 반환한다.

        language는 사용하지 않는다 — youtube-search-python이 언어 필터를
        제공하지 않고, 검색어 자체의 언어로 결과가 결정되기 때문이다.
        """
        try:
            from youtubesearchpython import VideosSearch

            raw = VideosSearch(query, limit=limit).result()
        except Exception as error:  # 스크래핑 라이브러리는 예외 종류가 다양하다.
            raise LatestProviderError(
                self.name,
                "request_failed",
                f"YouTube 검색에 실패했습니다: {error}",
            ) from error

        now = datetime.now(UTC)
        articles: list[LatestArticle] = []
        # raw.get("result", [])는 키가 없을 때만 기본값을 쓴다. 검색 결과가 없거나
        # 라이브러리 내부 오류 시 키는 있고 값이 None이므로 `or []`로 걸러야 한다.
        for item in raw.get("result") or []:
            url = str(item.get("link") or "").strip()
            if not url:
                continue
            published_time = str(item.get("publishedTime") or "")
            age_hours = relative_age_hours(published_time)
            published_at = now - timedelta(hours=age_hours) if age_hours is not None else None
            channel = (item.get("channel") or {}).get("name")
            articles.append(
                LatestArticle(
                    provider=self.name,
                    title=str(item.get("title") or ""),
                    url=url,
                    description=str(channel or ""),
                    published_at=published_at,
                    source_name=str(channel) if channel else None,
                    language=language,
                    source_url=url,
                )
            )
        return articles
