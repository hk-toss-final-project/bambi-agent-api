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

from agent.assistant import history
from agent.assistant.summarize import summarize_text

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


def search_videos(keyword: str, limit: int = 4) -> list[dict[str, object]]:
    """키워드로 YouTube 영상을 검색해 메타데이터 목록을 반환한다.

    Args:
        keyword: 검색어
        limit: 가져올 영상 수

    Returns:
        {video_id, title, url, channel, duration, published_time} 딕셔너리 리스트
    """
    from youtubesearchpython import VideosSearch

    raw = VideosSearch(keyword, limit=limit).result()
    # raw.get("result", [])는 키가 아예 없을 때만 기본값을 쓴다. 검색 결과가 없거나
    # youtubesearchpython 내부에서 오류가 나면 키는 있고 값이 None인 응답을 주므로,
    # `or []`로 None 값 자체를 걸러야 순회 시 TypeError가 나지 않는다.
    videos: list[dict[str, object]] = []
    for item in raw.get("result") or []:
        video_id = item.get("id")
        videos.append(
            {
                "video_id": video_id,
                "title": item.get("title"),
                "url": item.get("link"),
                "channel": (item.get("channel") or {}).get("name"),
                "duration": item.get("duration"),
                "published_time": item.get("publishedTime"),
                # video_id만으로 조립 가능한 공식 썸네일 URL (API 키 불필요).
                "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None,
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


def youtube_digest_for_user(
    keyword: str,
    user_id: str,
    limit: int = 4,
    model: str = "gpt-4.1-mini",
    max_age_hours: float = _DEFAULT_MAX_AGE_HOURS,
) -> list[dict[str, object]]:
    """사용자의 시청 이력을 반영해 개인화된 YouTube 요약 목록을 반환한다.

    첫 조회 여부와 무관하게 항상 최근(max_age_hours 이내) 영상만 후보로 삼고,
    그중 이미 본 영상은 제외한다. 기사·Reddit과 같은 최신성 기준을 공유한다.
    조건을 만족하는 새 영상이 없으면 빈 목록을 반환한다(새 소식 없음).
    """
    already_watched = history.get_watched_video_ids(user_id, keyword)

    pool_size = max(limit * 6, 18)
    pool = search_videos(keyword, limit=pool_size)
    recent = filter_recent_videos(pool, max_age_hours=max_age_hours)
    candidates = [video for video in recent if video.get("video_id") not in already_watched]

    selected = candidates[:limit]
    return _summarize_videos_with_delay(selected, model=model)
