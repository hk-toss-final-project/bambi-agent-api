"""YouTube 검색과 자막 요약.

키워드로 관련 영상을 검색(youtube-search-python)하고, 각 영상의 자막을
(youtube-transcript-api) 가져와 LLM으로 요약한다. 검색·자막 조회 등 네트워크
경계 함수를 분리해 테스트에서 대체할 수 있게 한다.

youtube-search-python은 정확한 발행 시각 대신 "19 hours ago", "1 day ago" 같은
상대 표현만 제공한다. 따라서 "어제 영상"은 이 상대 표현을 대략적인 경과 시간으로
환산해 최근 영상만 남기는 근사 필터로 처리한다(달력상 정확한 어제와 다를 수 있다).
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime

from agent.assistant.features.summarize import summarize_text

# 자막 조회 시 선호하는 언어 순서. 한국어 우선, 없으면 영어를 시도한다.
_PREFERRED_LANGUAGES = ("ko", "en")

# 영상별 자막 요청 사이에 두는 지연(초). 검색 1번에 자막 요청이 한꺼번에 몰리면
# YouTube가 짧은 시간 반복 요청으로 보고 IP를 일시 차단하는 경우가 있어, 요청
# 간격을 두어 그 위험을 낮춘다. (이미 차단된 상태를 풀어주지는 못한다.)
_TRANSCRIPT_REQUEST_DELAY_SECONDS = 1.5

# "어제 영상" 근사 기준. 상대 표현이 이 시간 이내면 최근 영상으로 본다.
# "1 day ago"가 실제로 24~47시간을 포함하므로 어제 업로드를 놓치지 않도록 48시간을 기본값으로 둔다.
_DEFAULT_MAX_AGE_HOURS = 48.0

# 상대 표현 단위를 시간으로 환산하는 표.
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


def _relative_age_hours(published_time: str) -> float | None:
    """'1 day ago' / '1일 전' 같은 상대 표현을 대략적인 경과 시간(시간 단위)으로 환산한다.

    해석할 수 없으면 None을 반환한다.
    """
    if not published_time:
        return None
    text = published_time.strip().lower()

    # 영어: "19 hours ago", "1 day ago"
    match = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s+ago", text)
    if match:
        return int(match.group(1)) * _UNIT_HOURS[match.group(2)]

    # 영어 단수: "a day ago", "an hour ago"
    match = re.search(r"\ba[n]?\s+(second|minute|hour|day|week|month|year)\s+ago", text)
    if match:
        return _UNIT_HOURS[match.group(1)]

    # 한국어: "19시간 전", "1일 전", "10개월 전", "6년 전"
    match = re.search(r"(\d+)\s*(초|분|시간|일|주|개월|달|년)\s*전", published_time)
    if match:
        return int(match.group(1)) * _KO_UNIT_HOURS[match.group(2)]

    return None


def filter_recent_videos(
    videos: list[dict[str, object]], max_age_hours: float = _DEFAULT_MAX_AGE_HOURS
) -> list[dict[str, object]]:
    """발행 경과 시간이 기준 이내인 영상만 남긴다.

    경과 시간을 알 수 없는(상대 표현을 해석하지 못한) 영상은 최근 여부를 확신할 수
    없으므로 제외한다.
    """
    recent: list[dict[str, object]] = []
    for video in videos:
        age = _relative_age_hours(str(video.get("published_time") or ""))
        if age is not None and age <= max_age_hours:
            recent.append(video)
    return recent


def _video_id_from_url(url: str) -> str | None:
    """YouTube URL에서 video_id를 뽑는다. 형식을 못 알아보면 None."""
    match = re.search(r"(?:v=|youtu\.be/|/shorts/)([\w-]{11})", url)
    return match.group(1) if match else None


def _relative_expression(published_at: "datetime | None") -> str:
    """발행 시각을 파이프라인이 파싱하는 상대 표현("3 hours ago")으로 되돌린다.

    Provider는 상대 표현을 시각으로 환산해 주지만, 비서 파이프라인은 다시 상대
    표현을 기대한다(_relative_age_hours). 두 변환이 같은 단위 표를 쓰므로
    왕복해도 경과 시간이 보존된다.
    """
    if published_at is None:
        return ""
    hours = max((datetime.now(UTC) - published_at).total_seconds() / 3600.0, 0.0)
    if hours < 1:
        return f"{max(int(hours * 60), 1)} minutes ago"
    if hours < 24:
        return f"{int(hours)} hours ago"
    return f"{int(hours // 24)} days ago"


def search_videos(keyword: str, limit: int = 4) -> list[dict[str, object]]:
    """키워드로 YouTube 영상을 검색해 메타데이터 목록을 반환한다.

    Args:
        keyword: 검색어
        limit: 가져올 영상 수

    Returns:
        {video_id, title, url, channel, duration, published_time} 딕셔너리 리스트

    검색 자체는 공용 수집 커넥터(YouTubeSearchProvider)에 위임한다 — Global 수집
    워커와 같은 코드를 써서 수집 경로가 갈라지지 않게 한다. 여기서는 비서
    파이프라인이 기대하는 딕셔너리 모양으로만 되돌린다.
    """
    import asyncio

    from infrastructure.sources.connectors.api import YouTubeSearchProvider

    articles = asyncio.run(
        YouTubeSearchProvider().search(query=keyword, limit=limit, language=None)
    )

    videos: list[dict[str, object]] = []
    for article in articles:
        video_id = _video_id_from_url(str(article.url))
        videos.append(
            {
                "video_id": video_id,
                "title": article.title,
                "url": article.url,
                "channel": article.source_name,
                "duration": None,
                # 파이프라인은 상대 표현을 다시 시간으로 환산하므로, Provider가
                # 계산한 published_at을 같은 의미의 상대 표현으로 되돌린다.
                "published_time": _relative_expression(article.published_at),
                "thumbnail_url": (
                    f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None
                ),
            }
        )
    return videos


def fetch_transcript(video_id: str, languages: tuple[str, ...] = _PREFERRED_LANGUAGES) -> str | None:
    """영상 자막을 텍스트로 합쳐 반환한다. 자막이 없으면 None을 반환한다.

    Args:
        video_id: YouTube 영상 ID
        languages: 선호 자막 언어 순서

    Returns:
        자막 전체 텍스트 또는 None
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    try:
        fetched = api.fetch(video_id, languages=list(languages))
    except Exception:
        # 선호 언어 자막이 없으면 사용 가능한 아무 자막이나 시도한다.
        try:
            transcript = next(iter(api.list(video_id)))
            fetched = transcript.fetch()
        except Exception:
            return None

    text = " ".join(snippet.text for snippet in fetched).strip()
    return text or None


def summarize_video(video: dict[str, object], model: str = "gpt-4.1-mini") -> dict[str, object]:
    """영상 하나의 자막을 요약해 결과 딕셔너리를 만든다.

    자막이 없으면 요약 대신 안내 문구를 넣는다.
    """
    video_id = str(video.get("video_id") or "")
    transcript = fetch_transcript(video_id) if video_id else None

    if transcript:
        summary = summarize_text(
            transcript,
            instruction=f"다음 유튜브 영상 '{video.get('title')}'의 자막을 요약해줘.",
            model=model,
        )
        note = None
    else:
        summary = None
        note = "자막이 없어 요약할 수 없습니다."

    return {
        "video_id": video_id,
        "title": video.get("title"),
        "url": video.get("url"),
        "channel": video.get("channel"),
        "duration": video.get("duration"),
        "published_time": video.get("published_time"),
        "thumbnail_url": video.get("thumbnail_url"),
        "summary": summary,
        "note": note,
    }


def _summarize_videos_with_delay(
    videos: list[dict[str, object]], model: str
) -> list[dict[str, object]]:
    """영상 목록을 순서대로 요약하되, 자막 요청 사이에 지연을 둔다.

    검색 1번에 자막 요청이 한꺼번에 몰려 YouTube의 IP 차단을 유발하는 것을
    막기 위한 완화책이다. 이미 차단된 상태에서는 효과가 없다.
    """
    results: list[dict[str, object]] = []
    for index, video in enumerate(videos):
        if index > 0:
            time.sleep(_TRANSCRIPT_REQUEST_DELAY_SECONDS)
        results.append(summarize_video(video, model=model))
    return results


def youtube_digest(
    keyword: str,
    limit: int = 4,
    model: str = "gpt-4.1-mini",
    max_age_hours: float = _DEFAULT_MAX_AGE_HOURS,
) -> list[dict[str, object]]:
    """키워드로 최근 영상을 검색하고 각 영상의 자막 요약 목록을 반환한다.

    최근 영상만 남기기 위해 검색 풀을 넉넉히 확보한 뒤 경과 시간으로 필터링하고,
    남은 영상 중 상위 limit개만 요약한다.
    """
    pool_size = max(limit * 4, 12)
    pool = search_videos(keyword, limit=pool_size)
    recent = filter_recent_videos(pool, max_age_hours=max_age_hours)[:limit]
    return _summarize_videos_with_delay(recent, model=model)
