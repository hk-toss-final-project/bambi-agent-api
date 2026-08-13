"""LLM이 스스로 도구를 골라 호출하는 실행 루프를 검증한다.

실제 LLM을 부르지 않도록 클라이언트를 대체하고, 응답 시나리오를 미리 짜서
루프가 도구를 실행하고 관찰을 되돌려주는지 확인한다.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent.llm.features.client import capture_llm_calls
from agent.llm.features import tool_loop
from agent.llm.features.tool_loop import ToolLoopResult, ToolSpec, run_tool_loop


class _FakeResponse:
    """tool_calls와 content를 갖는 LLM 응답 Test Double."""

    def __init__(
        self,
        *,
        content: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage_metadata = {"input_tokens": 10, "output_tokens": 5}


class _FakeClient:
    """정해진 응답을 순서대로 돌려주는 LLM 클라이언트 Test Double."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self.bound_schemas: list[dict[str, Any]] = []
        self.invocations: list[list[Any]] = []

    def bind_tools(self, schemas: list[dict[str, Any]]) -> "_FakeClient":
        """노출된 도구 스키마를 기록하고 자기 자신을 반환한다."""
        self.bound_schemas = schemas
        return self

    async def ainvoke(self, messages: list[Any]) -> _FakeResponse:
        """호출 시점의 대화를 기록하고 다음 응답을 반환한다."""
        self.invocations.append(list(messages))
        return self._responses.pop(0)


def _install(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    """도구 루프가 사용하는 LLM 클라이언트를 Test Double로 대체한다."""
    monkeypatch.setattr(tool_loop, "_get_client", lambda *args, **kwargs: client)


def _run(*args: Any, **kwargs: Any) -> ToolLoopResult:
    """비동기 도구 루프를 동기 테스트에서 실행한다."""
    return asyncio.run(run_tool_loop(*args, **kwargs))


def _echo_tool(calls: list[str]) -> ToolSpec:
    """호출을 기록하고 고정 관찰을 돌려주는 검색 도구를 만든다."""

    def run(query: str) -> str:
        """검색어를 기록하고 결과 문자열을 반환한다."""
        calls.append(query)
        return f"'{query}' 결과 2건"

    return ToolSpec(
        name="search_pool",
        description="창고에서 자료를 찾을 때 사용한다.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        run=run,
    )


def test_loop_runs_tool_then_returns_final_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """도구를 한 번 부르고 그 결과를 반영한 최종 답변을 반환한다."""
    queries: list[str] = []
    client = _FakeClient(
        [
            _FakeResponse(
                tool_calls=[
                    {"name": "search_pool", "args": {"query": "코스피"}, "id": "c1"}
                ]
            ),
            _FakeResponse(content="코스피 자료를 찾았습니다."),
        ]
    )
    _install(monkeypatch, client)

    result = _run(
        "너는 조사원이다.", "코스피 자료를 찾아라", [_echo_tool(queries)])

    assert queries == ["코스피"]
    assert result.text == "코스피 자료를 찾았습니다."
    assert result.stop_reason == "final"
    assert [call.name for call in result.calls] == ["search_pool"]
    assert result.calls[0].observation == "'코스피' 결과 2건"
    assert result.input_tokens == 20


def test_loop_records_each_provider_round_trip_as_tool_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """도구 선택과 최종 답변의 각 LLM 왕복을 별도 사용량 호출로 수집한다."""
    client = _FakeClient(
        [
            _FakeResponse(
                tool_calls=[
                    {"name": "search_pool", "args": {"query": "코스피"}, "id": "c1"}
                ]
            ),
            _FakeResponse(content="완료"),
        ]
    )
    _install(monkeypatch, client)

    with capture_llm_calls() as captured:
        _run("너는 조사원이다.", "조사", [_echo_tool([])])

    assert len(captured) == 2
    assert all(item.operation == "tool_completion" for item in captured)
    assert all(item.status == "succeeded" for item in captured)
    assert len({item.logical_call_id for item in captured}) == 2


def test_loop_lets_model_choose_a_follow_up_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """관찰을 보고 LLM이 다음 검색어를 스스로 정해 이어서 호출한다.

    흐름을 코드가 정하지 않는다는 것이 이 구조의 핵심이라 별도로 검증한다.
    """
    queries: list[str] = []
    client = _FakeClient(
        [
            _FakeResponse(
                tool_calls=[
                    {"name": "search_pool", "args": {"query": "코스피"}, "id": "c1"}
                ]
            ),
            _FakeResponse(
                tool_calls=[
                    {
                        "name": "search_pool",
                        "args": {"query": "서킷 브레이커"},
                        "id": "c2",
                    }
                ]
            ),
            _FakeResponse(content="두 건으로 충분합니다."),
        ]
    )
    _install(monkeypatch, client)

    result = _run(
        "너는 조사원이다.", "코스피 조사", [_echo_tool(queries)])

    assert queries == ["코스피", "서킷 브레이커"]
    assert len(result.calls) == 2
    assert result.stop_reason == "final"


def test_loop_reports_tool_failure_as_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """도구가 예외를 던져도 중단하지 않고 실패를 관찰로 전달한다."""

    def broken(query: str) -> str:
        """항상 실패하는 도구."""
        raise RuntimeError("연결 끊김")

    failing = ToolSpec(
        name="search_pool",
        description="창고 검색",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        run=broken,
    )
    client = _FakeClient(
        [
            _FakeResponse(
                tool_calls=[
                    {"name": "search_pool", "args": {"query": "코스피"}, "id": "c1"}
                ]
            ),
            _FakeResponse(content="자료 없이 답합니다."),
        ]
    )
    _install(monkeypatch, client)

    result = _run(
        "너는 조사원이다.", "코스피 조사", [failing])

    assert result.calls[0].failed is True
    assert "연결 끊김" in result.calls[0].observation
    assert result.text == "자료 없이 답합니다."


def test_loop_reports_unknown_tool_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """정의되지 않은 도구를 부르면 실패 관찰로 남기고 계속 진행한다."""
    client = _FakeClient(
        [
            _FakeResponse(
                tool_calls=[{"name": "search_web", "args": {}, "id": "c1"}]
            ),
            _FakeResponse(content="대신 이렇게 답합니다."),
        ]
    )
    _install(monkeypatch, client)

    result = _run(
        "너는 조사원이다.", "조사", [_echo_tool([])])

    assert result.calls[0].failed is True
    assert "search_web" in result.calls[0].observation
    assert result.text == "대신 이렇게 답합니다."


def test_loop_forces_a_final_answer_after_hitting_the_iteration_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """도구만 부르다 상한에 걸리면 도구 없이 한 번 더 물어 답을 받아낸다.

    실측(2026-08-11, `dup_reordered` 벤치 케이스)에서 같은 사실을 여러 번
    재검색하다 상한을 채워 최종 응답 자체가 사라진 사례가 나왔다. 관찰은 이미
    다 모았으므로 도구를 떼고 한 번 더 물으면 답을 건질 수 있어야 한다.
    """
    client = _FakeClient(
        [
            _FakeResponse(
                tool_calls=[
                    {"name": "search_pool", "args": {"query": f"q{n}"}, "id": f"c{n}"}
                ]
            )
            for n in range(3)
        ]
        + [_FakeResponse(content="관찰만으로 정리한 답변입니다.")]
    )
    _install(monkeypatch, client)

    result = _run(
        "너는 조사원이다.", "조사", [_echo_tool([])], max_iterations=3
    )

    assert result.stop_reason == "forced_final"
    assert result.text == "관찰만으로 정리한 답변입니다."
    # 강제 호출은 답을 받아내기 위한 것이지 도구 호출이 아니므로 기록에 안 남는다.
    assert len(result.calls) == 3
    # 상한(3) + 강제 호출(1) = 4번 호출, 토큰도 4번 치만큼 누적된다.
    assert result.input_tokens == 40


def test_loop_reports_max_iterations_if_the_forced_final_answer_is_also_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """강제로 한 번 더 물어도 빈 답이면 실패 사유를 그대로 남긴다."""
    client = _FakeClient(
        [
            _FakeResponse(
                tool_calls=[
                    {"name": "search_pool", "args": {"query": f"q{n}"}, "id": f"c{n}"}
                ]
            )
            for n in range(3)
        ]
        + [_FakeResponse(content="")]
    )
    _install(monkeypatch, client)

    result = _run(
        "너는 조사원이다.", "조사", [_echo_tool([])], max_iterations=3
    )

    assert result.stop_reason == "max_iterations"
    assert result.text == ""
    assert len(result.calls) == 3


def test_loop_exposes_tool_schemas_to_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """도구 정의가 OpenAI function 스키마로 모델에 전달된다."""
    client = _FakeClient([_FakeResponse(content="끝")])
    _install(monkeypatch, client)

    _run(
        "너는 조사원이다.", "조사", [_echo_tool([])])

    assert client.bound_schemas[0]["function"]["name"] == "search_pool"
    assert "창고" in client.bound_schemas[0]["function"]["description"]


def test_loop_skips_call_for_blank_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """빈 과제는 LLM을 부르지 않고 빈 결과를 반환한다."""
    client = _FakeClient([])
    _install(monkeypatch, client)

    result = _run(
        "너는 조사원이다.", "   ", [_echo_tool([])])

    assert result.text == ""
    assert result.calls == ()
    assert client.invocations == []
