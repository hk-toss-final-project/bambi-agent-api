"""PostgreSQL Provider RPM·TPM 예약과 응답 헤더 반영을 검증한다."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from infrastructure.persistence.features.provider_rate_limits import (
    observe_provider_rate_limits,
    parse_rate_limit_reset,
    reserve_provider_capacity,
)


class _FakeCursor:
    """고정 Row 하나를 반환하는 Cursor Test Double."""

    def __init__(self, row: dict[str, Any] | None = None) -> None:
        """반환할 Row를 보관한다."""
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        """보관한 Row를 반환한다."""
        return self._row


class _FakeConnection:
    """SQL과 인자를 기록하고 순서별 Row를 반환하는 연결 대역."""

    def __init__(self, rows: list[dict[str, Any] | None]) -> None:
        """순서별 Row와 빈 SQL 기록을 초기화한다."""
        self._rows = list(rows)
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    async def execute(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> _FakeCursor:
        """SQL을 기록하고 준비된 다음 Row를 반환한다."""
        self.executed.append((query, params))
        row = self._rows.pop(0) if self._rows else None
        return _FakeCursor(row)


def _stored_limit_row(**overrides: Any) -> dict[str, Any]:
    """현재 1분 Window의 Provider Rate Limit Row 예시를 만든다."""
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    row: dict[str, Any] = {
        "limit_requests": 60,
        "remaining_requests": 20,
        "reset_requests_at": now + timedelta(seconds=30),
        "limit_tokens": 60_000,
        "remaining_tokens": 40_000,
        "reset_tokens_at": now + timedelta(seconds=20),
        "blocked_until": None,
        "observed_at": now,
    }
    row.update(overrides)
    return row


def test_parse_rate_limit_reset_supports_compound_and_milliseconds() -> None:
    """OpenAI Reset 헤더의 복합 단위와 millisecond를 정확히 해석한다."""
    assert parse_rate_limit_reset("6m0s") == timedelta(minutes=6)
    assert parse_rate_limit_reset("500ms") == timedelta(milliseconds=500)
    assert parse_rate_limit_reset("invalid") is None


def test_reserve_provider_capacity_decrements_available_budget() -> None:
    """용량이 있으면 같은 Transaction에서 예상 요청과 Token을 차감한다."""
    connection = _FakeConnection([None, _stored_limit_row(), None])

    decision = asyncio.run(
        reserve_provider_capacity(
            connection,  # type: ignore[arg-type]
            provider="openai",
            resource_key="gpt-4.1-mini",
            request_count=3,
            estimated_tokens=10_000,
            default_rpm=60,
            default_tpm=60_000,
        )
    )

    assert decision.allowed is True
    assert decision.remaining_requests == 17
    assert decision.remaining_tokens == 30_000
    assert connection.executed[-1][1][0] == 17
    assert connection.executed[-1][1][2] == 30_000


def test_reserve_provider_capacity_returns_reset_without_decrement() -> None:
    """TPM이 부족하면 차감하지 않고 가장 늦은 관련 Reset 시각을 반환한다."""
    row = _stored_limit_row(remaining_tokens=5_000)
    connection = _FakeConnection([None, row, None])

    decision = asyncio.run(
        reserve_provider_capacity(
            connection,  # type: ignore[arg-type]
            provider="openai",
            resource_key="gpt-4.1-mini",
            request_count=3,
            estimated_tokens=10_000,
            default_rpm=60,
            default_tpm=60_000,
        )
    )

    assert decision.allowed is False
    assert decision.retry_at == row["reset_tokens_at"]
    assert decision.remaining_requests == 20
    assert decision.remaining_tokens == 5_000


def test_observe_provider_rate_limits_uses_response_headers() -> None:
    """실제 상한·잔여량·Reset과 Retry-After를 저장 상태에 반영한다."""
    connection = _FakeConnection([None, _stored_limit_row(), None])

    asyncio.run(
        observe_provider_rate_limits(
            connection,  # type: ignore[arg-type]
            provider="openai",
            resource_key="gpt-4.1-mini",
            headers={
                "x-ratelimit-limit-requests": "100",
                "x-ratelimit-remaining-requests": "90",
                "x-ratelimit-reset-requests": "1s",
                "x-ratelimit-limit-tokens": "90000",
                "x-ratelimit-remaining-tokens": "70000",
                "x-ratelimit-reset-tokens": "2s",
                "retry-after": "3",
            },
            request_id="req-123",
            default_rpm=60,
            default_tpm=60_000,
        )
    )

    params = connection.executed[-1][1]
    assert params is not None
    assert params[0:2] == (100, 90)
    assert params[3:5] == (90_000, 70_000)
    assert params[6] == 3.0
    assert params[9] == "req-123"
