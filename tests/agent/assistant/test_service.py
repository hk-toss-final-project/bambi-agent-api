"""비서 오케스트레이터(service) 검증. 실제 네트워크/LLM은 호출하지 않는다."""

import pytest

from agent.assistant.features import service


def test_assist_daily_agent_delegates_to_graph(monkeypatch) -> None:
    """assist_daily_agent는 리서치 에이전트 그래프에 위임하고 그 결과를 그대로 돌려준다."""
    captured: dict[str, object] = {}

    def fake_run_agent(topic, user_id, *, model="gpt-4.1-mini"):
        captured.update(topic=topic, user_id=user_id, model=model)
        return {"keyword": topic, "mode": "daily", "report_markdown": "브리핑", "agent_trace": ["단계"]}

    monkeypatch.setattr(service.graph, "run_agent", fake_run_agent)

    result = service.assist_daily_agent("전고체", user_id="minji", model="gpt-4.1-mini")

    assert captured == {"topic": "전고체", "user_id": "minji", "model": "gpt-4.1-mini"}
    assert result["report_markdown"] == "브리핑"
    assert result["agent_trace"] == ["단계"]


def _patch_article_history(monkeypatch, already_reported: set[str] | None = None) -> list[tuple]:
    """기사 보고 이력을 파일 대신 메모리로 대체하고, 기록 호출 내역을 반환한다."""
    recorded: list[tuple] = []
    monkeypatch.setattr(
        service.history, "get_reported_article_keys", lambda user_id, keyword: already_reported or set()
    )
    monkeypatch.setattr(
        service.history,
        "record_reported_article",
        lambda *args, **kwargs: recorded.append(args),
    )
    return recorded


def test_assist_combines_all_sources(monkeypatch) -> None:
    """YouTube·Reddit 요약과 기사 결과를 하나의 딕셔너리로 묶는다."""
    monkeypatch.setattr(
        service,
        "youtube_digest_for_user",
        lambda kw, user_id, limit=4, model="gpt-4.1-mini": [{"title": "영상"}],
    )
    monkeypatch.setattr(service, "reddit_digest", lambda kw, limit=4, model="gpt-4.1-mini": [{"title": "게시글"}])
    monkeypatch.setattr(
        service, "latest_articles", lambda kw, limit=6, exclude_urls=None: [{"title": "기사", "url": "https://a.com/1"}]
    )
    _patch_article_history(monkeypatch)

    result = service.assist("전고체 배터리", user_id="minji")

    assert result["keyword"] == "전고체 배터리"
    assert result["user_id"] == "minji"
    assert result["youtube"] == [{"title": "영상"}]
    assert result["reddit"] == [{"title": "게시글"}]
    assert result["articles"] == [{"title": "기사", "url": "https://a.com/1"}]
    assert result["errors"] == []


def test_assist_isolates_source_failure(monkeypatch) -> None:
    """한 소스(Reddit)가 실패해도 다른 결과는 반환하고 오류를 기록한다."""

    def boom(*args, **kwargs):
        raise RuntimeError("검색 오류")

    monkeypatch.setattr(
        service,
        "youtube_digest_for_user",
        lambda kw, user_id, limit=4, model="gpt-4.1-mini": [{"title": "영상"}],
    )
    monkeypatch.setattr(service, "reddit_digest", boom)
    monkeypatch.setattr(
        service, "latest_articles", lambda kw, limit=6, exclude_urls=None: [{"title": "기사", "url": "https://a.com/1"}]
    )
    _patch_article_history(monkeypatch)

    result = service.assist("키워드", user_id="minji")

    assert result["youtube"] == [{"title": "영상"}]
    assert result["reddit"] == []
    assert result["articles"] == [{"title": "기사", "url": "https://a.com/1"}]
    assert any("Reddit" in err for err in result["errors"])


def test_assist_passes_user_id_to_youtube(monkeypatch) -> None:
    """user_id가 YouTube 개인화 함수에 그대로 전달된다."""
    captured = {}

    def fake_youtube(kw, user_id, limit=4, model="gpt-4.1-mini"):
        captured["user_id"] = user_id
        return []

    monkeypatch.setattr(service, "youtube_digest_for_user", fake_youtube)
    monkeypatch.setattr(service, "reddit_digest", lambda kw, limit=4, model="gpt-4.1-mini": [])
    monkeypatch.setattr(service, "latest_articles", lambda kw, limit=6, exclude_urls=None: [])
    _patch_article_history(monkeypatch)

    service.assist("키워드", user_id="minji")

    assert captured["user_id"] == "minji"


def test_assist_passes_reported_history_to_articles(monkeypatch) -> None:
    """이미 보고한 기사 URL 집합이 latest_articles의 exclude_urls로 전달된다."""
    captured = {}

    def fake_articles(kw, limit=6, exclude_urls=None):
        captured["exclude_urls"] = exclude_urls
        return []

    monkeypatch.setattr(service, "youtube_digest_for_user", lambda kw, user_id, limit=4, model="gpt-4.1-mini": [])
    monkeypatch.setattr(service, "reddit_digest", lambda kw, limit=4, model="gpt-4.1-mini": [])
    monkeypatch.setattr(service, "latest_articles", fake_articles)
    _patch_article_history(monkeypatch, already_reported={"https://a.com/seen"})

    service.assist("키워드", user_id="minji")

    assert captured["exclude_urls"] == {"https://a.com/seen"}


def test_assist_records_reported_articles(monkeypatch) -> None:
    """리포트에 실은 기사가 정규 URL 키로 보고 이력에 기록된다."""
    monkeypatch.setattr(service, "youtube_digest_for_user", lambda kw, user_id, limit=4, model="gpt-4.1-mini": [])
    monkeypatch.setattr(service, "reddit_digest", lambda kw, limit=4, model="gpt-4.1-mini": [])
    monkeypatch.setattr(
        service,
        "latest_articles",
        lambda kw, limit=6, exclude_urls=None: [
            {"title": "기사1", "url": "https://a.com/1?utm=x"},
            {"title": "기사2", "url": "https://b.com/2"},
        ],
    )
    recorded = _patch_article_history(monkeypatch)

    service.assist("코스피", user_id="minji")

    assert recorded == [
        ("minji", "코스피", "https://a.com/1", "기사1", "https://a.com/1?utm=x"),
        ("minji", "코스피", "https://b.com/2", "기사2", "https://b.com/2"),
    ]


def test_assist_rejects_empty_keyword() -> None:
    """빈 키워드는 거부한다."""
    with pytest.raises(ValueError):
        service.assist("   ", user_id="minji")


def test_assist_rejects_empty_user_id() -> None:
    """빈 사용자 식별자는 거부한다."""
    with pytest.raises(ValueError):
        service.assist("키워드", user_id="   ")
