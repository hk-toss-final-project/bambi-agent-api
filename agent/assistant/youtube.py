"""YouTube 검색과 자막 요약.

키워드로 관련 영상을 검색(youtube-search-python)하고, 각 영상의 자막을
(youtube-transcript-api) 가져와 LLM으로 요약한다. 검색·자막 조회 등 네트워크
경계 함수를 분리해 테스트에서 대체할 수 있게 한다.
"""

from __future__ import annotations

from agent.assistant.summarize import summarize_text

# 자막 조회 시 선호하는 언어 순서. 한국어 우선, 없으면 영어를 시도한다.
_PREFERRED_LANGUAGES = ("ko", "en")


def search_videos(keyword: str, limit: int = 4) -> list[dict[str, object]]:
    """키워드로 YouTube 영상을 검색해 메타데이터 목록을 반환한다.

    Args:
        keyword: 검색어
        limit: 가져올 영상 수

    Returns:
        {video_id, title, url, channel, duration} 딕셔너리 리스트
    """
    from youtubesearchpython import VideosSearch

    raw = VideosSearch(keyword, limit=limit).result()
    videos: list[dict[str, object]] = []
    for item in raw.get("result", []):
        videos.append(
            {
                "video_id": item.get("id"),
                "title": item.get("title"),
                "url": item.get("link"),
                "channel": (item.get("channel") or {}).get("name"),
                "duration": item.get("duration"),
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
        "title": video.get("title"),
        "url": video.get("url"),
        "channel": video.get("channel"),
        "duration": video.get("duration"),
        "summary": summary,
        "note": note,
    }


def youtube_digest(keyword: str, limit: int = 4, model: str = "gpt-4.1-mini") -> list[dict[str, object]]:
    """키워드로 영상을 검색하고 각 영상의 자막 요약 목록을 반환한다."""
    videos = search_videos(keyword, limit=limit)
    return [summarize_video(video, model=model) for video in videos]
