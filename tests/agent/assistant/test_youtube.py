"""YouTube 검색·자막 요약(youtube) 검증. 실제 네트워크/LLM은 호출하지 않는다."""

from agent.assistant import youtube


def test_summarize_video_summarizes_when_transcript_exists(monkeypatch) -> None:
    """자막이 있으면 요약 함수를 호출해 summary를 채운다."""
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid, languages=("ko", "en"): "자막 텍스트")
    monkeypatch.setattr(youtube, "summarize_text", lambda text, instruction, model="gpt-4.1-mini": "요약 결과")

    video = {"video_id": "abc123", "title": "제목", "url": "https://youtu.be/abc123", "channel": "채널", "duration": "10:00"}
    result = youtube.summarize_video(video)

    assert result["summary"] == "요약 결과"
    assert result["note"] is None
    assert result["url"] == "https://youtu.be/abc123"


def test_summarize_video_notes_missing_transcript(monkeypatch) -> None:
    """자막이 없으면 요약 대신 안내 문구를 넣는다."""
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid, languages=("ko", "en"): None)

    called = {"summarize": False}

    def fail_summarize(*args, **kwargs):
        called["summarize"] = True
        return "should not run"

    monkeypatch.setattr(youtube, "summarize_text", fail_summarize)

    video = {"video_id": "abc123", "title": "제목", "url": "https://youtu.be/abc123"}
    result = youtube.summarize_video(video)

    assert result["summary"] is None
    assert "자막" in result["note"]
    assert called["summarize"] is False


def test_youtube_digest_maps_search_to_summaries(monkeypatch) -> None:
    """검색 결과 각각을 자막 요약으로 변환한다."""
    monkeypatch.setattr(
        youtube,
        "search_videos",
        lambda keyword, limit=4: [
            {"video_id": "v1", "title": "영상1", "url": "u1", "channel": "c1", "duration": "5:00"},
            {"video_id": "v2", "title": "영상2", "url": "u2", "channel": "c2", "duration": "3:00"},
        ],
    )
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid, languages=("ko", "en"): "자막")
    monkeypatch.setattr(youtube, "summarize_text", lambda text, instruction, model="gpt-4.1-mini": f"{instruction[:2]} 요약")

    digest = youtube.youtube_digest("키워드", limit=2)

    assert len(digest) == 2
    assert digest[0]["title"] == "영상1"
    assert digest[0]["summary"].endswith("요약")
