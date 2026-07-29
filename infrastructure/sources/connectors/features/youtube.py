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

검색 정렬: 기본 검색(VideosSearch)은 YouTube의 관련도순이라 "최근 + 주목받는"
영상을 뽑지 못한다. 2026-07-29 실측('AI 반도체'):

    관련도순              199회/2시간 전 무명 채널, 10개월 전 영상이 함께 섞임
    thisWeek + viewCount  MBCNEWS 22만회/3일 전, 18만회/3일 전 …

조회수 급등 여부를 우리가 계산하려면 조회수 이력을 쌓아야 하지만, 업로드 기간을
좁히고 조회수순으로 받으면 "최근에 많이 본 영상"을 YouTube 랭킹에서 그대로
얻는다. 그래서 검색 환경설정(CustomSearch)을 선택할 수 있게 열어 둔다. 아무것도
지정하지 않으면 기존 관련도순 그대로 동작한다.
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

# 검색 환경설정으로 지정할 수 있는 값. youtubesearchpython의 VideoUploadDateFilter·
# VideoSortOrder 속성 이름과 같으며, 잘못된 값을 조용히 무시하지 않도록 여기서
# 검사한다(오타가 나면 필터 없이 수집되어 원인을 찾기 어렵다).
UPLOAD_WINDOWS = ("lastHour", "today", "thisWeek", "thisMonth", "thisYear")
SORT_ORDERS = ("relevance", "uploadDate", "viewCount", "rating")


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

    def __init__(
        self,
        *,
        upload_window: str | None = None,
        sort_by: str | None = None,
    ) -> None:
        """검색 정렬 조건을 저장한다. 둘 다 생략하면 기존 관련도순 검색이다.

        Args:
            upload_window: 업로드 기간 필터 (UPLOAD_WINDOWS 중 하나). 예: "thisWeek"
            sort_by: 정렬 기준 (SORT_ORDERS 중 하나). 예: "viewCount"

        Raises:
            ValueError: 지원하지 않는 값을 넘겼을 때
        """
        if upload_window is not None and upload_window not in UPLOAD_WINDOWS:
            raise ValueError(
                f"지원하지 않는 upload_window입니다: {upload_window} "
                f"(가능: {', '.join(UPLOAD_WINDOWS)})"
            )
        if sort_by is not None and sort_by not in SORT_ORDERS:
            raise ValueError(
                f"지원하지 않는 sort_by입니다: {sort_by} (가능: {', '.join(SORT_ORDERS)})"
            )
        self._upload_window = upload_window
        self._sort_by = sort_by

    def _run_search(self, query: str, limit: int) -> dict:
        """정렬 조건 유무에 따라 알맞은 검색 방식으로 원본 응답을 받는다.

        정렬 조건이 없으면 기존과 같은 VideosSearch(관련도순)를, 있으면
        CustomSearch에 환경설정 문자열을 이어 붙여 넘긴다.
        """
        if self._upload_window is None and self._sort_by is None:
            from youtubesearchpython import VideosSearch

            return VideosSearch(query, limit=limit).result()

        from youtubesearchpython import (
            CustomSearch,
            VideoSortOrder,
            VideoUploadDateFilter,
        )

        # youtubesearchpython은 필터 상수를 이어 붙인 문자열 하나를 받는다.
        preferences = ""
        if self._upload_window is not None:
            preferences += getattr(VideoUploadDateFilter, self._upload_window)
        if self._sort_by is not None:
            preferences += getattr(VideoSortOrder, self._sort_by)
        return CustomSearch(query, preferences, limit=limit).result()

    async def search(
        self, *, query: str, limit: int, language: str | None
    ) -> list[LatestArticle]:
        """키워드로 영상을 검색해 최신 문서 목록을 반환한다.

        language는 사용하지 않는다 — youtube-search-python이 언어 필터를
        제공하지 않고, 검색어 자체의 언어로 결과가 결정되기 때문이다.
        """
        try:
            raw = self._run_search(query, limit)
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
