"""리서치 에이전트 그래프(graph) 검증. 실제 LLM·파이프라인은 대체한다.

run_daily(결정론 선별)와 complete(LLM)·generate_daily_report(보고서)를 대체해,
그래프의 흐름(선별→라우팅→재구성 루프→보고서)만 결정적으로 검증한다.
"""

from datetime import UTC, datetime

import pytest

from agent.assistant import graph

_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)


def _selection(mode: str, *, query: str, items: list | None = None) -> dict:
    """run_daily가 돌려주는 모양의 선별 결과를 만든다."""
    return {
        "keyword": "전고체",
        "user_id": "minji",
        "mode": mode,
        "cold_start": False,
        "items": items if items is not None else ([{"title": "아이템"}] if mode == "daily" else []),
        "log": {"collected": 3, "search_query": query},
        "errors": [],
    }


@pytest.fixture(autouse=True)
def _patch_report(monkeypatch):
    """보고서 생성을 고정 문자열로 대체한다(모든 테스트 공통)."""
    monkeypatch.setattr(graph, "generate_daily_report", lambda sel, model="gpt-4.1-mini": "보고서 본문")


def test_first_attempt_success_skips_reformulation(monkeypatch) -> None:
    """1차 검색에서 당일 아이템이 나오면 재구성 없이 바로 보고서로 간다."""
    calls: list[str] = []

    def fake_run_daily(topic, user_id, *, model="gpt-4.1-mini", reference_now=None, search_query=None):
        calls.append(search_query)
        return _selection("daily", query=search_query)

    monkeypatch.setattr(graph, "run_daily", fake_run_daily)
    monkeypatch.setattr(graph, "complete", lambda *a, **k: pytest.fail("재구성을 호출하면 안 된다"))

    result = graph.run_agent("전고체", "minji", reference_now=_NOW)

    assert result["mode"] == "daily"
    assert result["report_markdown"] == "보고서 본문"
    assert calls == ["전고체"]           # 토픽으로 1회만 시도
    assert result["attempts"] == ["전고체"]
    assert any("보고서 작성" in step for step in result["agent_trace"])
    # 판단 근거(몇 차 시도인지, 왜 재시도 없이 진행하는지)가 사람이 읽을 문장으로 남는다.
    judgment = next(step for step in result["agent_trace"] if step.startswith("판단"))
    assert "1차 시도" in judgment
    assert "재시도 없이" in judgment


def test_reformulates_when_thin_then_succeeds(monkeypatch) -> None:
    """1차가 빈약하면 LLM으로 검색어를 재구성해 2차 시도하고, 성공하면 보고서로 간다."""
    calls: list[str] = []

    def fake_run_daily(topic, user_id, *, model="gpt-4.1-mini", reference_now=None, search_query=None):
        calls.append(search_query)
        # 1차(토픽)는 빈약(weekly), 2차(재구성)는 성공(daily).
        mode = "daily" if search_query == "전고체 배터리 양산" else "weekly"
        return _selection(mode, query=search_query)

    monkeypatch.setattr(graph, "run_daily", fake_run_daily)
    monkeypatch.setattr(graph, "complete", lambda s, u, model="gpt-4.1-mini": "전고체 배터리 양산")

    result = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=2)

    assert result["mode"] == "daily"
    assert calls == ["전고체", "전고체 배터리 양산"]        # 토픽 → 재구성 검색어
    assert result["attempts"] == ["전고체", "전고체 배터리 양산"]
    # 재구성 trace에 원래 검색어→새 검색어 변화가 그대로 보인다(LLM 제안 채택).
    reform_step = next(step for step in result["agent_trace"] if "검색어 재구성" in step)
    assert "전고체" in reform_step and "전고체 배터리 양산" in reform_step
    # 재시도 판단 trace도 몇 차 시도인지·남은 재시도 횟수를 담는다.
    retry_judgment = next(step for step in result["agent_trace"] if step.startswith("판단(1차"))
    assert "재시도 여지가 남아" in retry_judgment


def test_exhausts_reformulations_and_falls_back(monkeypatch) -> None:
    """계속 빈약하면 재구성을 한도까지만 시도하고 폴백 보고서로 마무리한다."""
    calls: list[str] = []

    def fake_run_daily(topic, user_id, *, model="gpt-4.1-mini", reference_now=None, search_query=None):
        calls.append(search_query)
        return _selection("weekly", query=search_query)  # 늘 빈약

    reform_queries = iter(["재구성1", "재구성2", "재구성3"])
    monkeypatch.setattr(graph, "run_daily", fake_run_daily)
    monkeypatch.setattr(graph, "complete", lambda s, u, model="gpt-4.1-mini": next(reform_queries))

    result = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=2)

    # 1차(토픽) + 재구성 2회 = 총 3회 시도 후 종료.
    assert calls == ["전고체", "재구성1", "재구성2"]
    assert result["mode"] == "weekly"
    assert result["report_markdown"] == "보고서 본문"
    # 마지막(3차) 판단은 "한도를 모두 사용했다"는 종료 사유를 담는다.
    final_judgment = next(step for step in result["agent_trace"] if step.startswith("판단(3차"))
    assert "한도" in final_judgment and "모두 사용" in final_judgment


def test_no_reformulation_when_limit_zero(monkeypatch) -> None:
    """max_reformulations=0이면 빈약해도 재구성 없이 1회로 끝낸다."""
    calls: list[str] = []
    monkeypatch.setattr(
        graph, "run_daily",
        lambda topic, user_id, *, model="gpt-4.1-mini", reference_now=None, search_query=None:
            calls.append(search_query) or _selection("evergreen", query=search_query),
    )
    monkeypatch.setattr(graph, "complete", lambda *a, **k: pytest.fail("재구성 금지"))

    result = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=0)

    assert calls == ["전고체"]
    assert result["mode"] == "evergreen"


def test_reformulate_duplicate_suggestion_falls_back_to_topic(monkeypatch) -> None:
    """LLM이 이미 시도한 검색어를 다시 제안하면 토픽으로 되돌린다(같은 검색 반복 방지)."""
    calls: list[str] = []

    def fake_run_daily(topic, user_id, *, model="gpt-4.1-mini", reference_now=None, search_query=None):
        calls.append(search_query)
        return _selection("weekly", query=search_query)

    monkeypatch.setattr(graph, "run_daily", fake_run_daily)
    # LLM이 1차 검색어(토픽)와 같은 값을 제안 → 토픽으로 되돌아간다.
    monkeypatch.setattr(graph, "complete", lambda s, u, model="gpt-4.1-mini": "전고체")

    result = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=1)

    assert calls == ["전고체", "전고체"]  # 재구성이 토픽으로 폴백돼도 흐름은 유지
    assert result["mode"] == "weekly"


def test_reformulate_llm_failure_falls_back_to_topic(monkeypatch) -> None:
    """재구성 LLM 호출이 실패해도 예외 없이 토픽으로 되돌려 계속 진행한다."""
    monkeypatch.setattr(
        graph, "run_daily",
        lambda topic, user_id, *, model="gpt-4.1-mini", reference_now=None, search_query=None:
            _selection("weekly", query=search_query),
    )

    def boom(*a, **k):
        raise RuntimeError("LLM 오류")

    monkeypatch.setattr(graph, "complete", boom)

    result = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=1)

    assert result["mode"] == "weekly"          # 예외로 죽지 않고 폴백 보고서까지 완주
    assert result["report_markdown"] == "보고서 본문"


def test_run_agent_rejects_empty_inputs() -> None:
    """빈 토픽·빈 사용자 식별자는 거부한다."""
    with pytest.raises(ValueError):
        graph.run_agent("   ", "minji")
    with pytest.raises(ValueError):
        graph.run_agent("전고체", "   ")
