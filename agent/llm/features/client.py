"""공유 LLM Chat Completion 경계.

wiki_builder·report_builder 등 Agent 기능이 공통으로 사용하는 저수준 LLM 호출을
한 곳에 모은다. 일시적 Provider 오류 재시도(지수 Backoff), 요청 Timeout,
토큰 사용량 반환을 여기서만 처리해 각 도메인이 복원력 코드를 중복
구현하지 않게 한다. 테스트는 `_get_client`를 대체해 실제 호출을 막는다.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from time import monotonic
from typing import TypeVar

from shared.retry import exponential_backoff_delay, parse_retry_after_seconds

_DEFAULT_MODEL = "gpt-4.1-mini"
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_TIMEOUT_SECONDS = 120.0
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_MAX_RETRY_SECONDS = 60.0
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 30.0
_BACKOFF_JITTER_RATIO = 0.25

ResultT = TypeVar("ResultT")

# (model, temperature, timeout) 조합별로 클라이언트를 한 번만 생성해 재사용한다.
_clients: dict[tuple[str, float, float], object] = {}


@dataclass(frozen=True, slots=True)
class LlmCompletion:
    """LLM 호출 결과 텍스트와 토큰 사용량."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    request_id: str | None = None
    rate_limit_headers: dict[str, str] = field(default_factory=dict)


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
            include_response_headers=True,
        )
    return _clients[key]


def _response_headers(value: object) -> dict[str, str]:
    """SDK 응답 또는 예외에서 HTTP 응답 헤더를 소문자 Key로 추출한다."""
    response_metadata = getattr(value, "response_metadata", None)
    raw_headers: object = None
    if isinstance(response_metadata, Mapping):
        raw_headers = response_metadata.get("headers")
    if raw_headers is None:
        response = getattr(value, "response", None)
        raw_headers = getattr(response, "headers", None)
    if not isinstance(raw_headers, Mapping):
        return {}
    return {str(key).lower(): str(item) for key, item in raw_headers.items()}


def _provider_error_code(error: Exception) -> str:
    """OpenAI 오류 Body에서 quota·billing 판정에 사용할 Code를 추출한다."""
    direct = getattr(error, "code", None)
    if direct:
        return str(direct).strip().lower()
    body = getattr(error, "body", None)
    if isinstance(body, Mapping):
        nested = body.get("error")
        if isinstance(nested, Mapping) and nested.get("code"):
            return str(nested["code"]).strip().lower()
        if body.get("code"):
            return str(body["code"]).strip().lower()
    return ""


def is_retryable_openai_error(error: Exception) -> bool:
    """일시 오류만 재시도하고 quota·billing 오류는 사용자 조치 대상으로 남긴다."""
    code = _provider_error_code(error)
    action_required_codes = {
        "billing_hard_limit_reached",
        "billing_not_active",
        "insufficient_quota",
        "quota_exceeded",
    }
    return code not in action_required_codes


def retry_after_seconds_from_error(error: Exception) -> float | None:
    """Provider 오류의 Retry-After 헤더를 대기 초로 변환한다."""
    return parse_retry_after_seconds(_response_headers(error).get("retry-after"))


def _retry_delay_for_error(error: Exception, attempt: int) -> float:
    """Provider 오류와 시도 횟수로 다음 재시도 대기시간을 계산한다."""
    return exponential_backoff_delay(
        attempt,
        retry_after_seconds=retry_after_seconds_from_error(error),
        base_seconds=_BACKOFF_BASE_SECONDS,
        max_backoff_seconds=_BACKOFF_MAX_SECONDS,
        jitter_ratio=_BACKOFF_JITTER_RATIO,
    )


def _call_with_retry(
    operation: Callable[[], ResultT],
    *,
    max_attempts: int,
    max_retry_seconds: float,
) -> ResultT:
    """SDK 재시도를 끈 단일 호출에 Retry-After 우선 Backoff를 적용한다."""
    transient = _transient_error_types()
    started = monotonic()
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except transient as error:
            if attempt >= max_attempts or not is_retryable_openai_error(error):
                raise
            delay = _retry_delay_for_error(error, attempt)
            if monotonic() - started + delay > max_retry_seconds:
                raise
            time.sleep(delay)
    raise RuntimeError("도달할 수 없는 Provider 재시도 분기입니다.")


def complete_with_usage(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str = _DEFAULT_MODEL,
    temperature: float = _DEFAULT_TEMPERATURE,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    max_retry_seconds: float = _DEFAULT_MAX_RETRY_SECONDS,
) -> LlmCompletion:
    """재시도·Timeout을 적용해 호출하고 텍스트와 토큰 사용량을 반환한다.

    Args:
        system_prompt: system 역할 프롬프트
        user_prompt: user 역할 프롬프트. 공백뿐이면 호출 없이 빈 결과 반환
        model: 사용할 OpenAI 모델 이름
        temperature: 샘플링 온도
        timeout_seconds: 요청 제한 시간(초)
        max_attempts: 일시적 오류에 대한 최대 시도 횟수
        max_retry_seconds: 재시도 대기에 사용할 최대 누적 시간(초)

    Returns:
        응답 텍스트, 모델명과 입력·출력 토큰 수
    """
    if max_attempts < 1:
        raise ValueError("max_attempts는 1 이상이어야 합니다.")
    if max_retry_seconds < 0:
        raise ValueError("max_retry_seconds는 0 이상이어야 합니다.")
    if not user_prompt.strip():
        return LlmCompletion(text="", model=model, input_tokens=0, output_tokens=0)
    client = _get_client(model, temperature, timeout_seconds)
    response = _call_with_retry(
        lambda: client.invoke([("system", system_prompt), ("human", user_prompt)]),
        max_attempts=max_attempts,
        max_retry_seconds=max_retry_seconds,
    )
    usage = getattr(response, "usage_metadata", None) or {}
    headers = _response_headers(response)
    return LlmCompletion(
        text=str(response.content).strip(),
        model=model,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        request_id=headers.get("x-request-id"),
        rate_limit_headers={
            key: value for key, value in headers.items() if key.startswith("x-ratelimit-")
        },
    )


def complete(
    system_prompt: str, user_prompt: str, model: str = _DEFAULT_MODEL
) -> str:
    """system·user 프롬프트로 호출해 응답 텍스트만 반환한다.

    기존 호출부(wiki 분류, 리포트 생성)의 서명을 유지하는 호환 진입점이며,
    내부적으로 complete_with_usage의 재시도·Timeout을 그대로 적용한다.
    """
    return complete_with_usage(system_prompt, user_prompt, model=model).text
