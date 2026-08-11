"""외부 Provider 재시도 대기시간 계산 공통 함수.

OpenAI 동기 호출과 Worker Job 재시도가 같은 지수 Backoff·Retry-After 규칙을
사용하도록 순수 계산을 한 곳에 둔다.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


def parse_retry_after_seconds(
    value: object,
    *,
    now: datetime | None = None,
) -> float | None:
    """Retry-After 숫자 또는 HTTP-date를 0 이상의 대기 초로 변환한다."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        try:
            reset_at = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
        if reset_at.tzinfo is None:
            reset_at = reset_at.replace(tzinfo=UTC)
        current = now or datetime.now(UTC)
        seconds = (reset_at - current).total_seconds()
    if seconds < 0:
        return 0.0
    return seconds


def exponential_backoff_delay(
    attempt: int,
    *,
    retry_after_seconds: float | None = None,
    base_seconds: float = 1.0,
    max_backoff_seconds: float = 300.0,
    jitter_ratio: float = 0.25,
    random_source: Callable[[], float] = random.random,
) -> float:
    """시도 횟수에 따른 지수 Backoff와 양의 jitter를 계산한다.

    `retry_after_seconds`가 있으면 Provider가 제시한 최소 대기시간보다 짧아지지
    않는다. `max_backoff_seconds`는 자체 지수 Backoff 상한이며 Provider가 더 긴
    Retry-After를 보낸 경우에는 그 값을 우선한다.
    """
    if attempt < 1:
        raise ValueError("attempt는 1 이상이어야 합니다.")
    if base_seconds < 0 or max_backoff_seconds < 0:
        raise ValueError("Backoff 시간은 0 이상이어야 합니다.")
    if not 0 <= jitter_ratio <= 1:
        raise ValueError("jitter_ratio는 0에서 1 사이여야 합니다.")
    exponential = min(max_backoff_seconds, base_seconds * (2 ** (attempt - 1)))
    minimum = max(exponential, retry_after_seconds or 0.0)
    jitter = minimum * jitter_ratio * max(0.0, min(1.0, random_source()))
    return minimum + jitter
