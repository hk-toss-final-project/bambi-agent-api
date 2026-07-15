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


def test_render_markdown_converts_links_and_bullets() -> None:
    """마크다운 링크와 불릿을 클릭 가능한 HTML로 변환한다."""
    from app.assistant.web import _render_markdown

    md = "## 출처\n- [뉴스] [기사 제목](https://news.example/1)"
    html_out = _render_markdown(md)

    assert '<a href="https://news.example/1" target="_blank">기사 제목</a>' in html_out
    assert "<h2>출처</h2>" in html_out
    assert "<li>" in html_out
    # 원본 마크다운 링크 문법이 그대로 텍스트로 남지 않는다.
    assert "](https://news.example/1)" not in html_out
