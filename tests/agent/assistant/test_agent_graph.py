"""리서치 에이전트 그래프(graph) 검증. 실제 LLM·파이프라인은 대체한다.

run_daily(결정론 선별)와 complete(LLM)·generate_daily_report(보고서)를 대체해,
그래프의 흐름(선별→원인 분류→재시도 판단→재구성 루프→보고서)만 결정적으로
검증한다.
"""

from datetime import UTC, datetime

import pytest

from agent.assistant.features import graph, outcomes

_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)


def _selection(
    mode: str,
    *,
    query: str,
    items: list | None = None,
    errors: list | None = None,
    **log,
) -> dict:
    """run_daily가 돌려주는 모양의 선별 결과를 만든다.

    log 기본값은 "수집은 됐지만 유사도에서 전멸(low_relevance)" 상황이다 —
    재구성이 유효한 대표 케이스라 루프 검증의 기본 시나리오로 쓴다.
    """
    base_log = {
        "search_query": query,
        "source_attempted": 3,
        "source_failures": [],
        "collected": 3,
        "after_basic_filter": 3,
        "after_similarity_filter": 0,
        "exclusions": [],
    }
    base_log.update(log)
    return {
        "keyword": "전고체",
        "user_id": "minji",
        "mode": mode,
        "cold_start": False,
        "items": items if items is not None else ([{"title": "아이템"}] if mode == "daily" else []),
        "log": base_log,
        "errors": list(errors or []),
    }


@pytest.fixture(autouse=True)
def _patch_report(monkeypatch):
    """보고서 생성을 고정 문자열로 대체한다(모든 테스트 공통)."""
    monkeypatch.setattr(graph, "generate_daily_report", lambda sel, model="gpt-4.1-mini": "보고서 본문")


def _patch_run_daily(monkeypatch, handler) -> list[str]:
    """run_daily를 대체하고, 실제로 사용된 검색어 목록을 반환한다."""
    calls: list[str] = []

    def fake_run_daily(
        topic,
        user_id,
        *,
        model="gpt-4.1-mini",
        reference_now=None,
        search_query=None,
        record_history=True,
    ):
        calls.append(search_query)
        return handler(search_query, len(calls))

    monkeypatch.setattr(graph, "run_daily", fake_run_daily)
    return calls


def test_first_attempt_success_skips_reformulation(monkeypatch) -> None:
    """1차 검색에서 당일 아이템이 나오면 재구성 없이 바로 보고서로 간다."""
    calls = _patch_run_daily(monkeypatch, lambda q, n: _selection("daily", query=q))
    monkeypatch.setattr(graph, "complete", lambda *a, **k: pytest.fail("재구성을 호출하면 안 된다"))

    result = graph.run_agent("전고체", "minji", reference_now=_NOW)

    assert result["mode"] == "daily"
    assert result["outcome"] == outcomes.SUCCESS
    assert calls == ["전고체"]
    assert result["attempts"] == ["전고체"]
    judgment = next(e for e in result["agent_trace"] if e["message"].startswith("판단"))
    assert judgment["status"] == "ok"
    assert "재시도 없이" in judgment["message"]


def test_reformulates_when_thin_then_succeeds(monkeypatch) -> None:
    """관련도 부족이면 검색어를 재구성해 2차 시도하고, 성공하면 보고서로 간다."""
    calls = _patch_run_daily(
        monkeypatch,
        lambda q, n: _selection("daily" if q == "전고체 배터리 양산" else "weekly", query=q),
    )
    monkeypatch.setattr(graph, "complete", lambda s, u, model="gpt-4.1-mini": "전고체 배터리 양산")

    result = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=2)

    assert result["mode"] == "daily"
    assert calls == ["전고체", "전고체 배터리 양산"]
    reform = next(e for e in result["agent_trace"] if e["node"] == "reformulate")
    assert reform["status"] == "ok"
    assert reform["query"] == "전고체 배터리 양산"
    retry_judgment = next(
        e for e in result["agent_trace"] if e["node"] == "select" and e["status"] == "retry"
    )
    assert retry_judgment["reason"] == outcomes.LOW_RELEVANCE


# ── 재시도 판단이 원인을 구분하는지 (비용 증폭 방지) ────────────────────────


def test_provider_failure_does_not_trigger_reformulation(monkeypatch) -> None:
    """외부 소스 장애는 검색어 문제가 아니므로 재시도하지 않는다.

    수정 전에는 원인을 보지 않고 아이템 없음만으로 재구성해, 전체 소스가
    타임아웃인 상황에서도 파이프라인 3회 + 재구성 LLM 2회를 실행했다.
    """
    calls = _patch_run_daily(
        monkeypatch,
        lambda q, n: _selection(
            "weekly",
            query=q,
            errors=["뉴스 수집 실패: TimeoutError: timed out"],
            source_failures=["뉴스", "YouTube", "Reddit"],
            collected=0,
        ),
    )
    monkeypatch.setattr(graph, "complete", lambda *a, **k: pytest.fail("장애 시 재구성 금지"))

    result = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=2)

    assert calls == ["전고체"]                       # 파이프라인 1회만 실행
    assert result["outcome"] == outcomes.PROVIDER_FAILURE
    stop_event = next(e for e in result["agent_trace"] if e["status"] == "stop")
    assert "검색어를 바꿔도 해결되지 않는" in stop_event["message"]


def test_duplicate_only_does_not_trigger_reformulation(monkeypatch) -> None:
    """'이미 보고한 소식뿐'은 검색어로 해결되지 않으므로 재시도하지 않는다."""
    calls = _patch_run_daily(
        monkeypatch,
        lambda q, n: _selection(
            "weekly",
            query=q,
            collected=5,
            after_basic_filter=5,
            after_similarity_filter=4,
            clusters=2,
            exclusions=[{"stage": "dedup"}, {"stage": "dedup"}],
        ),
    )
    monkeypatch.setattr(graph, "complete", lambda *a, **k: pytest.fail("중복 시 재구성 금지"))

    result = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=2)

    assert calls == ["전고체"]
    assert result["outcome"] == outcomes.DUPLICATE_ONLY


def test_no_results_triggers_reformulation(monkeypatch) -> None:
    """수집 0건(장애 아님)은 검색어 문제일 수 있으므로 재구성한다."""
    calls = _patch_run_daily(
        monkeypatch, lambda q, n: _selection("evergreen", query=q, collected=0)
    )
    monkeypatch.setattr(graph, "complete", lambda s, u, model="gpt-4.1-mini": f"대안{len(calls)}")

    result = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=1)

    assert len(calls) == 2                          # 1차 + 재구성 1회
    assert result["outcome"] == outcomes.NO_RESULTS


# ── 같은 검색어 반복 금지 (2번 지적) ────────────────────────────────────────


def test_duplicate_suggestion_stops_instead_of_repeating_search(monkeypatch) -> None:
    """LLM이 이미 시도한 검색어를 제안하면 같은 검색을 반복하지 않고 종료한다.

    수정 전에는 토픽으로 되돌린 뒤 select로 다시 가서, 결과가 같음이 보장된
    검색을 한 번 더 실행했다(순수 비용 낭비).
    """
    calls = _patch_run_daily(monkeypatch, lambda q, n: _selection("weekly", query=q))
    monkeypatch.setattr(graph, "complete", lambda s, u, model="gpt-4.1-mini": "전고체")

    result = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=2)

    assert calls == ["전고체"]                       # 같은 검색어로 재실행하지 않는다
    assert result["attempts"] == ["전고체"]
    reform = next(e for e in result["agent_trace"] if e["node"] == "reformulate")
    assert reform["status"] == "failed"
    assert reform["reason"] == "duplicate_suggestion"
    assert result["report_markdown"] == "보고서 본문"  # 그래도 보고서는 만든다


def test_empty_suggestion_stops_instead_of_repeating_search(monkeypatch) -> None:
    """LLM이 빈 제안을 주면 재실행 없이 재구성 실패로 종료한다."""
    calls = _patch_run_daily(monkeypatch, lambda q, n: _selection("weekly", query=q))
    monkeypatch.setattr(graph, "complete", lambda s, u, model="gpt-4.1-mini": "   ")

    result = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=2)

    assert calls == ["전고체"]
    reform = next(e for e in result["agent_trace"] if e["node"] == "reformulate")
    assert reform["reason"] == "empty_suggestion"


def test_overlong_suggestion_stops_instead_of_searching_garbage(monkeypatch) -> None:
    """LLM이 검색어 대신 키워드 나열을 뱉으면 그걸로 검색하지 않고 종료한다.

    벤치마크에서 한 글자 주제('K')에 "케이팝 K-pop K드라마 …" 52자가 나온 사례를
    반영한 방어 장치다. 그대로 검색하면 무관한 결과만 나온다.
    """
    calls = _patch_run_daily(monkeypatch, lambda q, n: _selection("weekly", query=q))
    overlong = "케이팝 K-pop K드라마 K-컬처 K-뷰티 K-푸드 K-스타 K-콘텐츠 K-아이돌"
    assert len(overlong) > graph.MAX_QUERY_CHARS
    monkeypatch.setattr(graph, "complete", lambda s, u, model="gpt-4.1-mini": overlong)

    result = graph.run_agent("K", "minji", reference_now=_NOW, max_reformulations=2)

    assert calls == ["K"]                            # 긴 제안으로 재검색하지 않는다
    reform = next(e for e in result["agent_trace"] if e["node"] == "reformulate")
    assert reform["status"] == "failed"
    assert reform["reason"] == "too_long_suggestion"


def test_reformulate_llm_failure_stops_and_records_error(monkeypatch) -> None:
    """재구성 LLM 호출이 실패하면 재실행 없이 종료하고 오류를 남긴다."""
    calls = _patch_run_daily(monkeypatch, lambda q, n: _selection("weekly", query=q))

    def boom(*a, **k):
        raise RuntimeError("LLM 오류")

    monkeypatch.setattr(graph, "complete", boom)

    result = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=2)

    assert calls == ["전고체"]
    assert any("검색어 재구성 실패" in error for error in result["errors"])
    reform = next(e for e in result["agent_trace"] if e["node"] == "reformulate")
    assert reform["status"] == "failed" and reform["reason"] == "llm_error"


def test_exhausts_reformulations_and_falls_back(monkeypatch) -> None:
    """계속 빈약하면 재구성을 한도까지만 시도하고 폴백 보고서로 마무리한다."""
    reform_queries = iter(["재구성1", "재구성2", "재구성3"])
    calls = _patch_run_daily(monkeypatch, lambda q, n: _selection("weekly", query=q))
    monkeypatch.setattr(graph, "complete", lambda s, u, model="gpt-4.1-mini": next(reform_queries))

    result = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=2)

    assert calls == ["전고체", "재구성1", "재구성2"]  # 1차 + 재구성 2회
    assert result["mode"] == "weekly"
    final_judgment = [e for e in result["agent_trace"] if e["status"] == "stop"][-1]
    assert "재시도 한도" in final_judgment["message"]


def test_no_reformulation_when_limit_zero(monkeypatch) -> None:
    """max_reformulations=0이면 재구성 가능한 원인이어도 1회로 끝낸다."""
    calls = _patch_run_daily(monkeypatch, lambda q, n: _selection("evergreen", query=q, collected=0))
    monkeypatch.setattr(graph, "complete", lambda *a, **k: pytest.fail("재구성 금지"))

    result = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=0)

    assert calls == ["전고체"]
    assert result["mode"] == "evergreen"


# ── 시도별 상태 누적·구조화 trace (5번 지적) ────────────────────────────────


def test_errors_from_all_attempts_are_preserved(monkeypatch) -> None:
    """1차에서 난 오류가 2차 성공에 덮여 사라지지 않는다.

    수정 전에는 마지막 selection만 반환해, 첫 시도의 YouTube 타임아웃이
    최종 errors=[]로 사라졌다.
    """

    def handler(query, attempt):
        if attempt == 1:
            return _selection(
                "weekly", query=query, errors=["YouTube 수집 실패: TimeoutError: timed out"]
            )
        return _selection("daily", query=query)

    _patch_run_daily(monkeypatch, handler)
    monkeypatch.setattr(graph, "complete", lambda s, u, model="gpt-4.1-mini": "새 검색어")

    result = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=1)

    assert result["mode"] == "daily"                       # 2차는 성공했지만
    assert any("YouTube 수집 실패" in error for error in result["errors"])  # 1차 오류는 보존
    assert any("1차 시도" in error for error in result["errors"])           # 몇 차인지도 남는다


def test_attempt_records_capture_each_try(monkeypatch) -> None:
    """시도별 요약(검색어·원인·모드·아이템 수)이 순서대로 누적된다."""

    def handler(query, attempt):
        if attempt == 1:
            return _selection("weekly", query=query)
        return _selection("daily", query=query)

    _patch_run_daily(monkeypatch, handler)
    monkeypatch.setattr(graph, "complete", lambda s, u, model="gpt-4.1-mini": "새 검색어")

    records = graph.run_agent("전고체", "minji", reference_now=_NOW, max_reformulations=1)[
        "attempt_records"
    ]

    assert [r["query"] for r in records] == ["전고체", "새 검색어"]
    assert records[0]["outcome"] == outcomes.LOW_RELEVANCE
    assert records[1]["outcome"] == outcomes.SUCCESS
    assert records[1]["items"] == 1


def test_trace_events_are_structured(monkeypatch) -> None:
    """trace는 자유 문자열이 아니라 감사 가능한 구조화 이벤트다."""
    _patch_run_daily(monkeypatch, lambda q, n: _selection("daily", query=q))
    monkeypatch.setattr(graph, "complete", lambda *a, **k: "미사용")

    trace = graph.run_agent("전고체", "minji", reference_now=_NOW)["agent_trace"]

    assert trace and all(isinstance(event, dict) for event in trace)
    required = {"node", "status", "reason", "query", "errors", "duration_ms", "message"}
    for event in trace:
        assert required <= set(event)
    assert [e["node"] for e in trace][0] == "plan"
    assert [e["node"] for e in trace][-1] == "write_report"


def test_report_failure_is_recorded_as_failed_not_success(monkeypatch) -> None:
    """보고서 생성이 실패하면 trace에 실패로 기록하고 오류를 남긴다."""
    _patch_run_daily(monkeypatch, lambda q, n: _selection("daily", query=q))

    def boom(sel, model="gpt-4.1-mini"):
        raise RuntimeError("보고서 오류")

    monkeypatch.setattr(graph, "generate_daily_report", boom)

    result = graph.run_agent("전고체", "minji", reference_now=_NOW)

    assert result["report_markdown"] == ""
    write_event = next(e for e in result["agent_trace"] if e["node"] == "write_report")
    assert write_event["status"] == "failed"
    assert any("보고서 생성 실패" in error for error in result["errors"])


def test_empty_report_is_not_recorded_as_success(monkeypatch) -> None:
    """예외가 없어도 본문이 비어 나오면 성공으로 기록하지 않는다."""
    _patch_run_daily(monkeypatch, lambda q, n: _selection("daily", query=q))
    monkeypatch.setattr(graph, "generate_daily_report", lambda sel, model="gpt-4.1-mini": "   ")

    result = graph.run_agent("전고체", "minji", reference_now=_NOW)

    write_event = next(e for e in result["agent_trace"] if e["node"] == "write_report")
    assert write_event["status"] == "failed" and write_event["reason"] == "empty_report"


def test_run_agent_rejects_empty_inputs() -> None:
    """빈 토픽·빈 사용자 식별자는 거부한다."""
    with pytest.raises(ValueError):
        graph.run_agent("   ", "minji")
    with pytest.raises(ValueError):
        graph.run_agent("전고체", "   ")
