"""변경점 추적 웹 테스트 페이지(/changeHistory) 라우터를 검증한다.

화면이 보여주는 섹션 구분과 before/after 강조가 **저장된 markdown 한 장을
쪼갠 것**인지를 확인한다. 페이지가 별도 데이터를 만들어 내면 화면과 실제
발행 내용이 갈리기 때문이다.
"""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.routers.development.change_history_views import (
    _render_section,
    _split_into_sentences_with_citations,
    highlight_before_after,
    split_report_sections,
)

MARKDOWN = """## Overview

브리핑 [G1]

## 🔥 주요 업데이트

### 🔁 달라진 사실 (1건)

- **B사 HBM4 · 양산 일정** — `2026-2Q` → `2026-3Q` [G1]

### 🆕 새로 확인된 사실 (1건)

- **원달러 환율 · 환율 수준** — `1450원 돌파` [G2]

## 📅 타임라인

- **2026-08-04** — 연기 발표 [G1]

## 💡 시사점

공급 지연이 길어질 수 있습니다 [G1]."""


def _dev_client() -> TestClient:
    """개발 라우터가 활성화된 TestClient를 만든다."""
    return TestClient(create_app(Settings(environment="test", enable_dev_agent_api=True)))


def test_split_report_sections_returns_all_four_sections() -> None:
    """저장된 markdown을 네 섹션으로 쪼갠다."""
    sections = split_report_sections(MARKDOWN)

    assert [title for title, _ in sections] == [
        "Overview",
        "🔥 주요 업데이트",
        "📅 타임라인",
        "💡 시사점",
    ]
    assert "브리핑 [G1]" in sections[0][1]


def test_split_report_sections_keeps_plain_text_intact() -> None:
    """헤더가 없는 본문은 통째로 한 덩어리로 돌려준다."""
    assert split_report_sections("헤더 없는 본문") == [("본문", "헤더 없는 본문")]


def test_highlight_before_after_marks_both_values() -> None:
    """갱신 표기의 before/after를 각각 감싸되 값 자체는 바꾸지 않는다."""
    marked = highlight_before_after("양산 일정: `2026-2Q` → `2026-3Q`")

    assert '<span class="before">2026-2Q</span>' in marked
    assert '<span class="after">2026-3Q</span>' in marked


def test_page_renders_the_toggle_form() -> None:
    """페이지가 on/off 토글이 있는 실행 폼을 보여준다."""
    with _dev_client() as client:
        response = client.get("/changeHistory")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert 'name="change_history_enabled"' in body
    assert 'name="topic"' in body
    assert 'name="user_id"' in body


def test_page_is_absent_without_dev_flag() -> None:
    """개발 API 플래그가 없으면 테스트 페이지도 등록되지 않는다."""
    with TestClient(create_app(Settings(environment="test"))) as client:
        assert client.get("/changeHistory").status_code == 404


def test_changed_and_new_subsections_render_with_distinct_styles() -> None:
    """달라진 사실과 새로 확인된 사실이 화면에서도 갈라 보인다."""
    updates = dict(split_report_sections(MARKDOWN))["🔥 주요 업데이트"]

    rendered = _render_section("🔥 주요 업데이트", updates)

    assert '<h3 class="changed">🔁 달라진 사실 (1건)</h3>' in rendered
    assert '<h3 class="fresh">🆕 새로 확인된 사실 (1건)</h3>' in rendered
    # 갱신은 이전/오늘 대비로, 신규는 오늘 값 하나로 강조한다.
    assert '<span class="before">2026-2Q</span>' in rendered
    assert '<span class="after">2026-3Q</span>' in rendered
    assert '<span class="value">1450원 돌파</span>' in rendered


def test_single_value_line_is_not_marked_as_a_change() -> None:
    """값이 하나뿐인 줄(신규)은 이전/오늘 대비로 표시하지 않는다."""
    marked = highlight_before_after("환율 수준 — `1450원 돌파`")

    assert '<span class="value">1450원 돌파</span>' in marked
    assert "before" not in marked


def test_split_into_sentences_with_citations_keeps_citations_attached() -> None:
    """문장 마침표 뒤에 오는 [L1], [L2] 출처 인용구가 잘리지 않고 끝에 잘 붙어서 개행되는지 검증한다."""
    text = "확산되고 있습니다. [L1][L2] 시중은행의 정기예금 잔액이 증가했습니다 [L3]."
    sentences = _split_into_sentences_with_citations(text)
    assert len(sentences) == 2
    assert sentences[0] == "확산되고 있습니다. [L1][L2]"
    assert sentences[1] == "시중은행의 정기예금 잔액이 증가했습니다 [L3]."


def test_split_into_sentences_with_citations_handles_decimal_numbers() -> None:
    """43.3% 같은 소수점 숫자의 점(.)을 문장 종결로 착각해 자르지 않는지 검증한다."""
    text = "지지율이 43.3%로 최저치를 경신했다 [L1]. 코스피가 1.5% 상승했다."
    sentences = _split_into_sentences_with_citations(text)
    assert len(sentences) == 2
    assert sentences[0] == "지지율이 43.3%로 최저치를 경신했다 [L1]."
    assert sentences[1] == "코스피가 1.5% 상승했다."
