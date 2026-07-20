"""파이프라인 기반 일간 보고서(generate_daily_report) 검증. 실제 LLM은 호출하지 않는다."""

from agent.assistant import report


def _daily_result(items: list[dict[str, object]], mode: str = "daily") -> dict[str, object]:
    """generate_daily_report에 넣을 파이프라인 결과를 만든다."""
    return {"keyword": "전고체", "user_id": "minji", "mode": mode, "items": items}


def test_daily_report_renders_item_sections(monkeypatch) -> None:
    """아이템별 (제목/통합 요약/출처 링크/발행일/선정 사유)를 Markdown으로 렌더링한다."""
    items = [
        {
            "title": "전고체 양산 발표",
            "summary": "여러 매체가 같은 발표를 다뤘다.",
            "sources": [
                {"title": "기사1", "url": "https://a.com/1", "source_type": "news"},
                {"title": "영상1", "url": "https://youtu.be/1", "source_type": "youtube"},
            ],
            "published": "2026-07-20T09:00:00+00:00",
            "score": 0.87,
            "reason": "final_score 0.87 ≥ 기준 0.5 (클러스터 2건)",
            "status": "신규",
        }
    ]
    result = report.generate_daily_report(_daily_result(items))

    assert "# 전고체 — 오늘의 브리핑" in result
    assert "## 전고체 양산 발표" in result
    assert "여러 매체가 같은 발표를 다뤘다." in result
    assert "[뉴스] [기사1](https://a.com/1)" in result
    assert "[YouTube] [영상1](https://youtu.be/1)" in result
    assert "발행일: 2026-07-20" in result
    assert "선정 사유: final_score 0.87" in result
    assert "오늘 신규 소식 없음" not in result  # 폴백 라벨이 붙지 않는다


def test_daily_report_marks_update_items(monkeypatch) -> None:
    """후속 업데이트 아이템은 [업데이트] 표시를 붙인다."""
    items = [
        {"title": "후속 소식", "summary": "요약", "sources": [], "published": "", "score": 0.6,
         "reason": "이유", "status": "업데이트"},
    ]
    result = report.generate_daily_report(_daily_result(items))

    assert "[업데이트]" in result


def test_weekly_fallback_has_label_and_issue_links(monkeypatch) -> None:
    """주간 트렌드 폴백은 상단 라벨을 명시하고 이슈 링크를 붙인다."""
    captured: dict[str, str] = {}

    def fake_complete(system_prompt, user_prompt, model="gpt-4.1-mini"):
        captured["user"] = user_prompt
        return "주간 트렌드 본문"

    monkeypatch.setattr(report, "complete", fake_complete)

    items = [{"title": "이슈1", "url": "https://a.com/1", "score": 0.9}]
    result = report.generate_daily_report(_daily_result(items, mode="weekly"))

    assert "오늘 신규 소식 없음 — 주간 트렌드 요약" in result
    assert "주간 트렌드 본문" in result
    assert "[이슈1](https://a.com/1)" in result
    assert "이슈1" in captured["user"]  # 이슈 목록이 프롬프트에 들어간다


def test_evergreen_fallback_has_label(monkeypatch) -> None:
    """에버그린 폴백은 '개념 정리' 라벨을 명시하고 딥다이브 본문을 쓴다."""
    monkeypatch.setattr(report, "complete", lambda s, u, model="gpt-4.1-mini": "개념 딥다이브 본문")

    result = report.generate_daily_report(_daily_result([], mode="evergreen"))

    assert "오늘 신규 소식 없음 — 개념 정리" in result
    assert "개념 딥다이브 본문" in result
