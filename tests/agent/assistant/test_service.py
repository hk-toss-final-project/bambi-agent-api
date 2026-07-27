"""비서 오케스트레이터(service) 검증. 실제 네트워크/LLM은 호출하지 않는다."""

from agent.assistant.features import service


def test_assist_daily_agent_delegates_to_graph(monkeypatch) -> None:
    """assist_daily_agent는 리서치 에이전트 그래프에 위임하고 그 결과를 그대로 돌려준다."""
    captured: dict[str, object] = {}

    def fake_run_agent(topic, user_id, *, model="gpt-4.1-mini", record_history=True, include_report=True):
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
