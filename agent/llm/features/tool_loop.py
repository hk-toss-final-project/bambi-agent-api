"""LLM Tool Calling 실행 루프.

LLM에게 도구 목록을 주고, **어떤 도구를 몇 번 호출할지 LLM이 스스로 정하게**
하는 순환을 구현한다. 호출 결과(관찰)를 다시 대화에 넣어 다음 행동을 정하게
하므로, 실행 흐름을 코드가 미리 정하는 고정 파이프라인과 구분된다.

호출자는 `ToolSpec`으로 도구를 정의하고 `run_tool_loop`에 넘긴다. 반환값에는
최종 답변뿐 아니라 **어떤 도구를 어떤 인자로 불렀는지 기록(trace)**이 함께
담긴다 — 벤치마크와 장애 분석이 이 기록에 의존한다.

실제 LLM 호출은 client 모듈의 재시도·Timeout 경계를 그대로 재사용한다.
테스트는 `_get_client`를 대체해 실제 호출을 막는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Any

from .client import (
    _DEFAULT_MODEL,
    _DEFAULT_MAX_RETRY_SECONDS,
    _DEFAULT_TIMEOUT_SECONDS,
    _get_client,
    _retry_delay_for_error,
    _transient_error_types,
    is_retryable_openai_error,
    record_llm_call_observation,
)

logger = logging.getLogger("agent.llm.tool_loop")

_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_MAX_ITERATIONS = 4
_DEFAULT_MAX_ATTEMPTS = 3
_MAX_OBSERVATION_CHARS = 6000


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """LLM에게 노출할 도구 하나의 정의.

    Attributes:
        name: LLM이 호출에 사용할 도구 이름
        description: 언제 이 도구를 써야 하는지 설명. LLM의 선택 근거가 되므로
            "무엇을 하는지"보다 "언제 쓰는지"를 적는 편이 낫다.
        parameters: 인자 JSON Schema (OpenAI function 형식)
        run: 실제 실행 함수. 인자를 키워드로 받아 관찰 문자열을 반환한다.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[..., str | Awaitable[str]]


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """LLM이 실행한 도구 호출 한 건의 기록."""

    name: str
    arguments: dict[str, Any]
    observation: str
    failed: bool = False


@dataclass(frozen=True, slots=True)
class ToolLoopResult:
    """도구 루프 실행 결과.

    Attributes:
        text: LLM의 최종 응답 텍스트
        calls: 실행한 도구 호출 기록(순서 보존)
        stop_reason: "final"(LLM이 도구를 더 안 부름) 또는
            "max_iterations"(반복 상한에 걸려 중단)
        input_tokens: 누적 입력 토큰
        output_tokens: 누적 출력 토큰
    """

    text: str
    calls: tuple[ToolCallRecord, ...] = field(default_factory=tuple)
    stop_reason: str = "final"
    input_tokens: int = 0
    output_tokens: int = 0


def _to_openai_schema(tool: ToolSpec) -> dict[str, Any]:
    """ToolSpec을 OpenAI function calling 스키마로 변환한다."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


async def _invoke_with_retry(
    client: Any,
    messages: list[Any],
    max_attempts: int,
    max_retry_seconds: float = _DEFAULT_MAX_RETRY_SECONDS,
) -> Any:
    """일시적 Provider 오류에 Retry-After 우선 Backoff를 적용해 호출한다."""
    transient = _transient_error_types()
    waited = 0.0
    for attempt in range(1, max_attempts + 1):
        try:
            return await client.ainvoke(messages)
        except transient as error:
            if attempt >= max_attempts or not is_retryable_openai_error(error):
                raise
            delay = _retry_delay_for_error(error, attempt)
            if waited + delay > max_retry_seconds:
                raise
            await asyncio.sleep(delay)
            waited += delay
    raise RuntimeError("도달할 수 없는 분기입니다.")


async def _execute_tool(
    tool: ToolSpec, arguments: Mapping[str, Any]
) -> tuple[str, bool]:
    """도구를 실행해 관찰 문자열과 실패 여부를 반환한다.

    도구가 예외를 던져도 루프를 중단하지 않는다. 실패 사실을 관찰로 돌려주면
    LLM이 다른 도구를 고르거나 그대로 답할 수 있기 때문이다. 여기서 예외를
    올리면 그 판단 기회 자체가 사라진다.

    동기·비동기 도구를 모두 받는다 — 풀 검색은 DB를 await 하지만 실시간 수집은
    동기 함수라 둘이 섞이기 때문이다.
    """
    try:
        observation = tool.run(**dict(arguments))
        if isawaitable(observation):
            observation = await observation
    except Exception as error:  # noqa: BLE001 - 도구 실패를 관찰로 전달한다
        logger.warning("도구 실행 실패: %s (%s)", tool.name, error)
        return f"도구 '{tool.name}' 실행에 실패했습니다: {error}", True
    text = observation if isinstance(observation, str) else str(observation)
    if len(text) > _MAX_OBSERVATION_CHARS:
        text = text[:_MAX_OBSERVATION_CHARS] + "\n…(관찰 결과가 길어 잘림)"
    return text, False


async def run_tool_loop(
    system_prompt: str,
    user_prompt: str,
    tools: Sequence[ToolSpec],
    *,
    model: str = _DEFAULT_MODEL,
    temperature: float = _DEFAULT_TEMPERATURE,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
) -> ToolLoopResult:
    """LLM이 스스로 도구를 골라 호출하는 순환을 실행한다.

    LLM이 도구 호출을 요청하면 실행해 결과를 대화에 덧붙이고 다시 묻는다.
    도구를 더 부르지 않으면 그 응답을 최종 답변으로 본다.

    Args:
        system_prompt: 역할과 도구 사용 지침
        user_prompt: 이번에 해결할 과제. 공백뿐이면 호출 없이 빈 결과 반환
        tools: 노출할 도구 목록. 비어 있으면 일반 Completion과 같다.
        model: 사용할 OpenAI 모델 이름
        temperature: 샘플링 온도. 도구 선택은 흔들리지 않는 편이 좋아 기본 0.0
        timeout_seconds: 요청 제한 시간(초)
        max_iterations: 도구 호출 왕복 상한. 무한 반복을 막는 안전장치다.
        max_attempts: 일시적 Provider 오류에 대한 최대 시도 횟수

    Returns:
        최종 텍스트, 도구 호출 기록, 중단 사유와 누적 토큰 사용량
    """
    if max_iterations < 1:
        raise ValueError("max_iterations는 1 이상이어야 합니다.")
    if not user_prompt.strip():
        return ToolLoopResult(text="")

    tools_by_name = {tool.name: tool for tool in tools}
    client = _get_client(model, temperature, timeout_seconds)
    if tools:
        client = client.bind_tools([_to_openai_schema(tool) for tool in tools])

    messages: list[Any] = [
        ("system", system_prompt),
        ("human", user_prompt),
    ]
    calls: list[ToolCallRecord] = []
    input_tokens = 0
    output_tokens = 0
    stop_reason = "max_iterations"
    text = ""

    for _ in range(max_iterations):
        response = await _invoke_with_retry(client, messages, max_attempts)
        usage = getattr(response, "usage_metadata", None) or {}
        input_tokens += int(usage.get("input_tokens") or 0)
        output_tokens += int(usage.get("output_tokens") or 0)
        record_llm_call_observation(
            model=model,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            value=response,
        )
        messages.append(response)

        tool_calls = list(getattr(response, "tool_calls", None) or [])
        if not tool_calls:
            text = str(response.content).strip()
            stop_reason = "final"
            break

        for tool_call in tool_calls:
            name = str(tool_call.get("name", ""))
            arguments = dict(tool_call.get("args") or {})
            tool = tools_by_name.get(name)
            if tool is None:
                observation, failed = f"알 수 없는 도구입니다: {name}", True
            else:
                observation, failed = await _execute_tool(tool, arguments)
            calls.append(
                ToolCallRecord(
                    name=name,
                    arguments=arguments,
                    observation=observation,
                    failed=failed,
                )
            )
            messages.append(_tool_message(observation, tool_call.get("id")))
    else:
        # 상한까지 도구만 부르고 끝났다. 마지막 응답 텍스트라도 살려 둔다.
        logger.warning("도구 루프가 %d회 반복 상한에 도달했습니다.", max_iterations)

    return ToolLoopResult(
        text=text,
        calls=tuple(calls),
        stop_reason=stop_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _tool_message(observation: str, tool_call_id: Any) -> Any:
    """도구 실행 결과를 대화에 넣을 ToolMessage로 만든다."""
    from langchain_core.messages import ToolMessage

    return ToolMessage(content=observation, tool_call_id=str(tool_call_id or ""))


def format_arguments(arguments: Mapping[str, Any]) -> str:
    """도구 인자를 로그·기록용 한 줄 문자열로 만든다."""
    return json.dumps(dict(arguments), ensure_ascii=False, sort_keys=True)
