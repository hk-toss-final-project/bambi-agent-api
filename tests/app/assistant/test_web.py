"""키워드 비서 웹 라우터 검증. 실제 네트워크/LLM은 호출하지 않는다."""

from fastapi.testclient import TestClient

from app.main import create_app


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


def test_friendly_reason_translates_known_codes() -> None:
    """제외 사유 원인 코드를 일반인이 읽을 수 있는 한국어 문장으로 바꾼다."""
    from agent.assistant.features import config
    from app.assistant.web import _friendly_reason

    outside_window = _friendly_reason("outside_window")
    assert "수집 기간" in outside_window
    assert f"{config.COLLECT_WINDOW_DAYS}일" in outside_window
    assert "관련성" in _friendly_reason("low_similarity(0.42 < 0.50)")
    assert "0.42" in _friendly_reason("low_similarity(0.42 < 0.50)")
    assert "이미 실은 소식" in _friendly_reason("already_reported(0.91, 기존: 어제 보고한 기사)")
    assert "못 미쳐" in _friendly_reason("below_threshold(0.31 < 0.45)")
    assert "0.31" in _friendly_reason("below_threshold(0.31 < 0.45)")
    assert "중복" in _friendly_reason("duplicate_url")
    assert "재수집" in _friendly_reason("url_already_collected")
    assert "짧아" in _friendly_reason("too_short")
    assert "링크 정보가 없는" in _friendly_reason("no_url")


def test_friendly_reason_falls_back_to_raw_code_when_unknown() -> None:
    """알려지지 않은 새 사유 코드는 원문을 그대로 보여준다(조용히 사라지지 않게)."""
    from app.assistant.web import _friendly_reason

    assert _friendly_reason("brand_new_reason_code") == "brand_new_reason_code"


def _trace_event(node, status, **extra) -> dict:
    """구조화된 trace 이벤트 하나를 만든다(렌더링 테스트용)."""
    event = {
        "node": node,
        "status": status,
        "reason": "",
        "query": "",
        "errors": [],
        "duration_ms": 0,
        "message": "",
    }
    event.update(extra)
    return event


def test_render_agent_section_shows_structured_trace() -> None:
    """구조화 trace의 라벨·상태 뱃지·원인 코드·소요 시간·오류를 렌더링한다."""
    from app.assistant.web import _render_agent_section

    result = {
        "agent_trace": [
            _trace_event(
                "plan", "ok", message="검색어 계획: 주제 '전고체'로 1차 검색을 시작합니다."
            ),
            _trace_event(
                "select",
                "retry",
                reason="low_relevance",
                duration_ms=1200,
                message="판단(1차 시도): 관련도가 기준에 못 미쳤습니다. 재구성합니다.",
            ),
            _trace_event(
                "select",
                "failed",
                reason="provider_failure",
                errors=["뉴스 수집 실패: TimeoutError"],
                message="수집·선별: 실패했습니다.",
            ),
        ],
        "attempts": ["전고체", "전고체 배터리 양산"],
    }

    html_out = _render_agent_section(result)

    assert "⓪ 에이전트 판단 과정" in html_out
    assert "<strong>검색어 계획:</strong>" in html_out
    assert "재시도" in html_out and "trace-retry" in html_out  # 상태 뱃지
    assert "원인 low_relevance" in html_out
    assert "1200ms" in html_out
    assert "뉴스 수집 실패: TimeoutError" in html_out           # 이벤트별 오류 노출
    assert "<code>전고체</code> → <code>전고체 배터리 양산</code>" in html_out


def test_render_agent_section_tolerates_plain_string_trace() -> None:
    """구조화 이전 형식(문자열) trace가 들어와도 깨지지 않는다."""
    from app.assistant.web import _render_agent_section

    html_out = _render_agent_section(
        {"agent_trace": ["검색어 계획: 주제 '전고체'로 시작합니다."], "attempts": ["전고체"]}
    )

    assert "<strong>검색어 계획:</strong>" in html_out


def test_render_agent_section_omits_attempts_line_when_single_try() -> None:
    """재구성이 없었으면(1회 시도) '시도한 검색어' 줄을 생략한다."""
    from app.assistant.web import _render_agent_section

    result = {
        "agent_trace": [_trace_event("plan", "ok", message="검색어 계획: 시작합니다.")],
        "attempts": ["전고체"],
    }

    assert "시도한 검색어" not in _render_agent_section(result)


def test_render_agent_section_empty_when_no_trace() -> None:
    """trace가 없으면 섹션 자체를 렌더링하지 않는다."""
    from app.assistant.web import _render_agent_section

    assert _render_agent_section({}) == ""


def test_form_page_renders() -> None:
    """루트 페이지는 사용자·키워드 입력 폼을 반환한다."""
    client = TestClient(create_app())
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

    monkeypatch.setattr(web_module, "assist_daily_agent", lambda keyword, *, user_id: fake_result)

    client = TestClient(create_app())
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

    monkeypatch.setattr(web_module, "assist_daily_agent", lambda keyword, *, user_id: fake_result)

    client = TestClient(create_app())
    response = client.post("/search", data={"user_id": "minji", "keyword": "전고체"})

    assert response.status_code == 200
    assert "주간 트렌드 요약" in response.text
    assert "이슈1" in response.text
