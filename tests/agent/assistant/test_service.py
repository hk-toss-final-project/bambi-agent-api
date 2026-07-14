"""비서 오케스트레이터(service) 검증. 실제 네트워크/LLM은 호출하지 않는다."""

import pytest

from agent.assistant import service


def test_assist_combines_all_sources(monkeypatch) -> None:
    """YouTube·Reddit 요약과 기사 결과를 하나의 딕셔너리로 묶는다."""
    monkeypatch.setattr(
        service,
        "youtube_digest_for_user",
        lambda kw, user_id, limit=4, model="gpt-4.1-mini": [{"title": "영상"}],
    )
    monkeypatch.setattr(service, "reddit_digest", lambda kw, limit=4, model="gpt-4.1-mini": [{"title": "게시글"}])
    monkeypatch.setattr(service, "latest_articles", lambda kw, limit=6: [{"title": "기사"}])

    result = service.assist("전고체 배터리", user_id="minji")

    assert result["keyword"] == "전고체 배터리"
    assert result["user_id"] == "minji"
    assert result["youtube"] == [{"title": "영상"}]
    assert result["reddit"] == [{"title": "게시글"}]
    assert result["articles"] == [{"title": "기사"}]
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
    monkeypatch.setattr(service, "latest_articles", lambda kw, limit=6: [{"title": "기사"}])

    result = service.assist("키워드", user_id="minji")

    assert result["youtube"] == [{"title": "영상"}]
    assert result["reddit"] == []
    assert result["articles"] == [{"title": "기사"}]
    assert any("Reddit" in err for err in result["errors"])


def test_assist_passes_user_id_to_youtube(monkeypatch) -> None:
    """user_id가 YouTube 개인화 함수에 그대로 전달된다."""
    captured = {}

    def fake_youtube(kw, user_id, limit=4, model="gpt-4.1-mini"):
        captured["user_id"] = user_id
        return []

    monkeypatch.setattr(service, "youtube_digest_for_user", fake_youtube)
    monkeypatch.setattr(service, "reddit_digest", lambda kw, limit=4, model="gpt-4.1-mini": [])
    monkeypatch.setattr(service, "latest_articles", lambda kw, limit=6: [])

    service.assist("키워드", user_id="minji")

    assert captured["user_id"] == "minji"


def test_assist_rejects_empty_keyword() -> None:
    """빈 키워드는 거부한다."""
    with pytest.raises(ValueError):
        service.assist("   ", user_id="minji")


def test_assist_rejects_empty_user_id() -> None:
    """빈 사용자 식별자는 거부한다."""
    with pytest.raises(ValueError):
        service.assist("키워드", user_id="   ")
