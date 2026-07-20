"""공유 LLM Chat Completion 경계.

wiki_builder·bambi 등 Agent 기능이 공통으로 사용하는 저수준 LLM 호출을
한 곳에 모은다. 일시적 Provider 오류 재시도(지수 Backoff), 요청 Timeout,
토큰 사용량 반환을 여기서만 처리해 각 도메인이 복원력 코드를 중복
구현하지 않게 한다. 테스트는 `_get_client`를 대체해 실제 호출을 막는다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

_DEFAULT_MODEL = "gpt-4.1-mini"
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_TIMEOUT_SECONDS = 120.0
_DEFAULT_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.0

# (model, temperature, timeout) 조합별로 클라이언트를 한 번만 생성해 재사용한다.
_clients: dict[tuple[str, float, float], object] = {}


@dataclass(frozen=True, slots=True)
class LlmCompletion:
    """LLM 호출 결과 텍스트와 토큰 사용량."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int


def _transient_error_types() -> tuple[type[Exception], ...]:
    """재시도 가능한 일시적 Provider 오류 타입을 반환한다."""
    from openai import (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )

    return (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)


def _get_client(model: str, temperature: float, timeout_seconds: float) -> object:
    """설정 조합에 해당하는 ChatOpenAI 클라이언트를 캐시에서 반환한다."""
    key = (model, temperature, timeout_seconds)
    if key not in _clients:
        from langchain_openai import ChatOpenAI

        # 재시도는 이 모듈의 Backoff 루프가 단독으로 담당하므로
        # SDK 내장 재시도는 꺼서 시도 횟수가 곱해지지 않게 한다.
        _clients[key] = ChatOpenAI(
            model=model,
            temperature=temperature,
            timeout=timeout_seconds,
            max_retries=0,
        )
    return _clients[key]


def complete_with_usage(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str = _DEFAULT_MODEL,
    temperature: float = _DEFAULT_TEMPERATURE,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
) -> LlmCompletion:
    """재시도·Timeout을 적용해 호출하고 텍스트와 토큰 사용량을 반환한다.

    Args:
        system_prompt: system 역할 프롬프트
        user_prompt: user 역할 프롬프트. 공백뿐이면 호출 없이 빈 결과 반환
        model: 사용할 OpenAI 모델 이름
        temperature: 샘플링 온도
        timeout_seconds: 요청 제한 시간(초)
        max_attempts: 일시적 오류에 대한 최대 시도 횟수

    Returns:
        응답 텍스트, 모델명과 입력·출력 토큰 수
    """
    if max_attempts < 1:
        raise ValueError("max_attempts는 1 이상이어야 합니다.")
    if not user_prompt.strip():
        return LlmCompletion(text="", model=model, input_tokens=0, output_tokens=0)
    client = _get_client(model, temperature, timeout_seconds)
    transient = _transient_error_types()
    response = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.invoke(
                [("system", system_prompt), ("human", user_prompt)]
            )
            break
        except transient:
            if attempt >= max_attempts:
                raise
            time.sleep(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
    usage = getattr(response, "usage_metadata", None) or {}
    return LlmCompletion(
        text=str(response.content).strip(),
        model=model,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
    )


def complete(
    system_prompt: str, user_prompt: str, model: str = _DEFAULT_MODEL
) -> str:
    """system·user 프롬프트로 호출해 응답 텍스트만 반환한다.

    기존 호출부(wiki 분류, bambi 생성)의 서명을 유지하는 호환 진입점이며,
    내부적으로 complete_with_usage의 재시도·Timeout을 그대로 적용한다.
    """
    return complete_with_usage(system_prompt, user_prompt, model=model).text
