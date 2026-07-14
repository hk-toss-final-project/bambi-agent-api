"""YouTube 검색·자막 요약(youtube) 검증. 실제 네트워크/LLM은 호출하지 않는다."""

import pytest

from agent.assistant import youtube


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch):
    """영상 사이 지연을 0으로 만들어 테스트가 실제로 기다리지 않게 한다."""
    monkeypatch.setattr(youtube, "_TRANSCRIPT_REQUEST_DELAY_SECONDS", 0)


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


def test_youtube_digest_keeps_only_recent_videos(monkeypatch) -> None:
    """최근 영상만 남기고 오래된 영상은 요약 대상에서 제외한다."""
    monkeypatch.setattr(
        youtube,
        "search_videos",
        lambda keyword, limit=4: [
            {"video_id": "v1", "title": "어제 영상", "url": "u1", "channel": "c1", "duration": "5:00", "published_time": "1 day ago"},
            {"video_id": "v2", "title": "오래된 영상", "url": "u2", "channel": "c2", "duration": "3:00", "published_time": "3 weeks ago"},
            {"video_id": "v3", "title": "오늘 영상", "url": "u3", "channel": "c3", "duration": "2:00", "published_time": "5 hours ago"},
        ],
    )
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid, languages=("ko", "en"): "자막")
    monkeypatch.setattr(youtube, "summarize_text", lambda text, instruction, model="gpt-4.1-mini": "요약")

    digest = youtube.youtube_digest("키워드", limit=5, max_age_hours=48)

    titles = [item["title"] for item in digest]
    assert "어제 영상" in titles
    assert "오늘 영상" in titles
    assert "오래된 영상" not in titles


def test_relative_age_hours_parses_english_and_korean() -> None:
    """영어·한국어 상대 표현을 경과 시간으로 환산한다."""
    assert youtube._relative_age_hours("19 hours ago") == 19
    assert youtube._relative_age_hours("1 day ago") == 24
    assert youtube._relative_age_hours("a day ago") == 24
    assert youtube._relative_age_hours("3 weeks ago") == 24 * 7 * 3
    assert youtube._relative_age_hours("1일 전") == 24
    assert youtube._relative_age_hours("19시간 전") == 19
    assert youtube._relative_age_hours("") is None
    assert youtube._relative_age_hours("방송 예정") is None


def test_filter_recent_videos_excludes_unparseable_and_old() -> None:
    """경과 시간을 알 수 없거나 기준을 넘는 영상을 제외한다."""
    videos = [
        {"title": "최근", "published_time": "10 hours ago"},
        {"title": "오래됨", "published_time": "2 months ago"},
        {"title": "알수없음", "published_time": "라이브 스트림"},
        {"title": "필드없음"},
    ]
    kept = [v["title"] for v in youtube.filter_recent_videos(videos, max_age_hours=48)]
    assert kept == ["최근"]


def test_digest_for_user_expands_query_on_first_visit(monkeypatch) -> None:
    """시청 이력이 없는 첫 조회는 날짜 제한 없이 입문성 검색어까지 확장한다."""
    from agent.assistant import history

    monkeypatch.setattr(history, "get_watched_video_ids", lambda user_id, keyword: set())

    calls: list[str] = []

    def fake_search(query, limit=4):
        calls.append(query)
        if "란 무엇인가" in query:
            return [{"video_id": "intro-1", "title": "입문 영상", "url": "u", "published_time": "3 months ago"}]
        return [{"video_id": "raw-1", "title": "일반 영상", "url": "u2", "published_time": "10 days ago"}]

    monkeypatch.setattr(youtube, "search_videos", fake_search)
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid, languages=("ko", "en"): "자막")
    monkeypatch.setattr(youtube, "summarize_text", lambda text, instruction, model="gpt-4.1-mini": "요약")

    digest = youtube.youtube_digest_for_user("전고체", "minji", limit=4)

    assert any("란 무엇인가" in query for query in calls)
    # 오래된 영상(3개월 전)도 첫 조회에서는 날짜 제한 없이 포함된다.
    titles = [item["title"] for item in digest]
    assert "입문 영상" in titles
    assert "일반 영상" in titles


def test_summarize_videos_with_delay_sleeps_between_but_not_before_first(monkeypatch) -> None:
    """영상이 여러 개면 사이마다 지연을 두되, 첫 영상 앞에는 기다리지 않는다."""
    monkeypatch.setattr(youtube, "_TRANSCRIPT_REQUEST_DELAY_SECONDS", 5)
    sleep_calls: list[float] = []
    monkeypatch.setattr(youtube.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid, languages=("ko", "en"): "자막")
    monkeypatch.setattr(youtube, "summarize_text", lambda text, instruction, model="gpt-4.1-mini": "요약")

    videos = [{"video_id": f"v{i}", "title": f"영상{i}", "url": f"u{i}"} for i in range(3)]
    youtube._summarize_videos_with_delay(videos, model="gpt-4.1-mini")

    assert sleep_calls == [5, 5]  # 영상 3개 -> 지연은 사이사이 2번만


def test_digest_for_user_excludes_watched_on_return_visit(monkeypatch) -> None:
    """시청 이력이 있으면 최근 영상 중 이미 본 영상을 제외한다."""
    from agent.assistant import history

    monkeypatch.setattr(history, "get_watched_video_ids", lambda user_id, keyword: {"v1"})
    monkeypatch.setattr(
        youtube,
        "search_videos",
        lambda query, limit=4: [
            {"video_id": "v1", "title": "이미 봄", "url": "u1", "published_time": "5 hours ago"},
            {"video_id": "v2", "title": "새 영상", "url": "u2", "published_time": "10 hours ago"},
            {"video_id": "v3", "title": "오래됨", "url": "u3", "published_time": "10 days ago"},
        ],
    )
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid, languages=("ko", "en"): "자막")
    monkeypatch.setattr(youtube, "summarize_text", lambda text, instruction, model="gpt-4.1-mini": "요약")

    digest = youtube.youtube_digest_for_user("전고체", "minji", limit=4, max_age_hours=48)

    titles = [item["title"] for item in digest]
    assert titles == ["새 영상"]
