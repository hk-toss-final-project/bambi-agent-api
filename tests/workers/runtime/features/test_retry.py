"""WC-007 Retry-After 우선 지수 Backoff를 검증한다."""

import asyncio
from datetime import UTC, datetime

import pytest

from shared.retry import exponential_backoff_delay, parse_retry_after_seconds
from workers.runtime.features.retry import wc_007


def test_wc_007_uses_exponential_delay_with_positive_jitter() -> None:
    """시도 횟수에 따라 지수 증가하고 jitter는 음수가 되지 않는다."""
    delay = asyncio.run(wc_007(3, base_seconds=1, jitter_ratio=0.25))

    assert 4 <= delay <= 5


def test_backoff_treats_retry_after_as_minimum() -> None:
    """Provider Retry-After가 자체 Backoff보다 길면 최소 대기시간으로 사용한다."""
    delay = exponential_backoff_delay(
        1,
        retry_after_seconds=10,
        base_seconds=1,
        jitter_ratio=0.25,
        random_source=lambda: 0.5,
    )

    assert delay == 11.25


def test_parse_retry_after_supports_seconds_and_http_date() -> None:
    """숫자 초와 HTTP-date 형식을 모두 해석한다."""
    now = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)

    assert parse_retry_after_seconds("2.5", now=now) == 2.5
    assert (
        parse_retry_after_seconds("Tue, 11 Aug 2026 00:00:05 GMT", now=now)
        == 5
    )
    assert parse_retry_after_seconds("invalid", now=now) is None


def test_backoff_rejects_invalid_attempt() -> None:
    """시도 번호가 1보다 작으면 계산하지 않는다."""
    with pytest.raises(ValueError, match="attempt"):
        asyncio.run(wc_007(0))
