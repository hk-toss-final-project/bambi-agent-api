"""키워드 비서 웹 라우터(/watch 시청 기록 리다이렉트) 검증."""

from fastapi.testclient import TestClient

from app.assistant.main import create_web_app


def test_watch_redirect_records_history_and_redirects(monkeypatch) -> None:
    """/watch는 시청 이력을 기록한 뒤 실제 영상 URL로 302 리다이렉트한다."""
    from app.assistant import web as web_module

    recorded: dict[str, object] = {}

    def fake_record_watch(user_id, keyword, video_id, title, url):
        recorded.update(user_id=user_id, keyword=keyword, video_id=video_id, title=title, url=url)

    monkeypatch.setattr(web_module.history, "record_watch", fake_record_watch)

    client = TestClient(create_web_app())
    response = client.get(
        "/watch",
        params={
            "user_id": "minji",
            "keyword": "전고체 배터리",
            "video_id": "abc123",
            "url": "https://youtu.be/abc123",
            "title": "제목",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://youtu.be/abc123"
    assert recorded == {
        "user_id": "minji",
        "keyword": "전고체 배터리",
        "video_id": "abc123",
        "title": "제목",
        "url": "https://youtu.be/abc123",
    }
