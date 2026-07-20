"""키워드 비서 웹 라우터 검증. 실제 네트워크/LLM은 호출하지 않는다."""

from fastapi.testclient import TestClient

from app.assistant.main import create_web_app


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


def test_render_markdown_blockquote_becomes_banner() -> None:
    """인용(>) 줄은 폴백 라벨 배너로 변환한다."""
    from app.assistant.web import _render_markdown

    html_out = _render_markdown("> **오늘 신규 소식 없음 — 개념 정리**")

    assert 'class="banner"' in html_out
    assert "개념 정리" in html_out
    assert "&gt;" not in html_out  # 인용 마커가 그대로 노출되지 않는다


def test_form_page_renders() -> None:
    """루트 페이지는 사용자·키워드 입력 폼을 반환한다."""
    client = TestClient(create_web_app())
    response = client.get("/")

    assert response.status_code == 200
    assert 'action="/search"' in response.text
    assert 'name="keyword"' in response.text


def test_search_renders_both_sections(monkeypatch) -> None:
    """검색 결과 페이지는 ① 수집·선별 내역과 ② 보고서를 함께 렌더링한다."""
    from app.assistant import web as web_module

    fake_result = {
        "keyword": "전고체",
        "user_id": "minji",
        "mode": "daily",
        "cold_start": False,
        "items": [
            {
                "title": "전고체 양산 발표",
                "status": "신규",
                "score": 0.812,
                "score_detail": {
                    "content_type": "news",
                    "similarity": 0.92,
                    "freshness": 0.9,
                    "source_weight": 0.8,
                    "cluster_boost": 1.1,
                    "final_score": 0.812,
                },
                "published": "2026-07-20T09:00:00+00:00",
                "published_method": "pub_date",
                "cluster_size": 2,
                "sources": [
                    {"title": "기사A", "url": "https://news.example/a", "source_type": "news"},
                ],
            }
        ],
        "log": {
            "collected": 10,
            "after_basic_filter": 8,
            "after_similarity_filter": 5,
            "clusters": 3,
            "exclusions": [
                {"stage": "similarity_filter", "reason": "low_similarity(0.42)", "title": "무관 기사"},
            ],
        },
        "errors": [],
        "report_markdown": "# 전고체 — 오늘의 브리핑\n\n## 전고체 양산 발표\n\n요약 본문.",
    }

    monkeypatch.setattr(web_module, "assist_daily", lambda keyword, *, user_id: fake_result)

    client = TestClient(create_web_app())
    response = client.post("/search", data={"user_id": "minji", "keyword": "전고체"})

    assert response.status_code == 200
    body = response.text
    # ① 수집·선별 내역
    assert "① 수집·선별 내역" in body
    assert "전고체 양산 발표" in body
    assert "0.812" in body                       # 최종 점수 노출
    assert "https://news.example/a" in body      # 실제 수집 출처 링크
    assert "제외 내역 1건" in body                # 제외 로그
    # ② 보고서
    assert "② 보고서" in body
    assert "요약 본문." in body


def test_search_shows_fallback_mode(monkeypatch) -> None:
    """당일 아이템이 없으면 워터폴 폴백 모드(주간 트렌드)를 표시한다."""
    from app.assistant import web as web_module

    fake_result = {
        "keyword": "전고체",
        "user_id": "minji",
        "mode": "weekly",
        "cold_start": False,
        "items": [{"url_key": "k", "title": "이슈1", "url": "https://a.com/1", "score": 0.9}],
        "log": {"collected": 4, "after_basic_filter": 0, "exclusions": []},
        "errors": [],
        "report_markdown": "# 전고체 — 오늘의 브리핑\n\n> **오늘 신규 소식 없음 — 주간 트렌드 요약**\n\n트렌드 본문.",
    }

    monkeypatch.setattr(web_module, "assist_daily", lambda keyword, *, user_id: fake_result)

    client = TestClient(create_web_app())
    response = client.post("/search", data={"user_id": "minji", "keyword": "전고체"})

    assert response.status_code == 200
    assert "주간 트렌드 요약" in response.text
    assert "이슈1" in response.text
