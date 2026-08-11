"""외부 Provider RPM·TPM 상태의 PostgreSQL 예약과 응답 헤더 반영.

Worker 인스턴스들이 같은 Provider 제한을 공유하되, 외부 API를 기다리는 동안
DB Lock을 유지하지 않도록 예약·관찰을 각각 짧은 Transaction에서 수행한다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from shared.retry import parse_retry_after_seconds

type DictRow = dict[str, Any]

_RESET_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ProviderRateLimitDecision:
    """Provider 용량 예약 결과와 다음 판단 시각."""

    allowed: bool
    retry_at: datetime | None
    remaining_requests: int
    remaining_tokens: int


def parse_rate_limit_reset(value: object) -> timedelta | None:
    """OpenAI reset 헤더의 `1s`, `6m0s`, `500ms` 형식을 시간 간격으로 바꾼다."""
    text = str(value or "").strip().lower()
    if not text:
        return None
    position = 0
    seconds = 0.0
    multipliers = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    for match in _RESET_PART.finditer(text):
        if match.start() != position:
            return None
        seconds += float(match.group(1)) * multipliers[match.group(2).lower()]
        position = match.end()
    if position != len(text):
        return None
    return timedelta(seconds=seconds)


def _positive_header_int(headers: Mapping[str, str], key: str) -> int | None:
    """헤더 값을 0 이상의 정수로 변환하고 잘못된 값은 무시한다."""
    try:
        value = int(headers[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if value >= 0 else None


async def reserve_provider_capacity(
    connection: AsyncConnection[DictRow],
    *,
    provider: str,
    resource_key: str,
    request_count: int,
    estimated_tokens: int,
    default_rpm: int,
    default_tpm: int,
) -> ProviderRateLimitDecision:
    """Provider·모델 Row를 잠그고 예상 요청·Token 용량을 원자적으로 예약한다."""
    if not provider or not resource_key:
        raise ValueError("Provider Rate Limit Key는 빈 문자열이면 안 됩니다.")
    if request_count < 1 or estimated_tokens < 0:
        raise ValueError("요청 수는 1 이상이고 예상 Token은 0 이상이어야 합니다.")
    if default_rpm < 1 or default_tpm < 1:
        raise ValueError("기본 RPM과 TPM은 1 이상이어야 합니다.")
    await connection.execute(
        """
        INSERT INTO agent.provider_rate_limits (
            provider,
            resource_key,
            limit_requests,
            remaining_requests,
            reset_requests_at,
            limit_tokens,
            remaining_tokens,
            reset_tokens_at
        ) VALUES (
            %s, %s, %s, %s, clock_timestamp() + interval '1 minute',
            %s, %s, clock_timestamp() + interval '1 minute'
        )
        ON CONFLICT (provider, resource_key) DO NOTHING
        """,
        (provider, resource_key, default_rpm, default_rpm, default_tpm, default_tpm),
    )
    cursor = await connection.execute(
        """
        SELECT
            limit_requests,
            remaining_requests,
            reset_requests_at,
            limit_tokens,
            remaining_tokens,
            reset_tokens_at,
            blocked_until,
            clock_timestamp() AS observed_at
        FROM agent.provider_rate_limits
        WHERE provider = %s AND resource_key = %s
        FOR UPDATE
        """,
        (provider, resource_key),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("Provider Rate Limit 상태를 생성하지 못했습니다.")
    now = row["observed_at"]
    limit_requests = int(row["limit_requests"])
    limit_tokens = int(row["limit_tokens"])
    remaining_requests = int(row["remaining_requests"])
    remaining_tokens = int(row["remaining_tokens"])
    reset_requests_at = row["reset_requests_at"]
    reset_tokens_at = row["reset_tokens_at"]
    blocked_until = row.get("blocked_until")
    if reset_requests_at <= now:
        remaining_requests = limit_requests
        reset_requests_at = now + timedelta(minutes=1)
    if reset_tokens_at <= now:
        remaining_tokens = limit_tokens
        reset_tokens_at = now + timedelta(minutes=1)
    reserved_requests = min(request_count, limit_requests)
    reserved_tokens = min(estimated_tokens, limit_tokens)
    blocked = blocked_until is not None and blocked_until > now
    allowed = (
        not blocked
        and remaining_requests >= reserved_requests
        and remaining_tokens >= reserved_tokens
    )
    retry_candidates: list[datetime] = []
    if blocked:
        retry_candidates.append(blocked_until)
    if remaining_requests < reserved_requests:
        retry_candidates.append(reset_requests_at)
    if remaining_tokens < reserved_tokens:
        retry_candidates.append(reset_tokens_at)
    if allowed:
        remaining_requests -= reserved_requests
        remaining_tokens -= reserved_tokens
    await connection.execute(
        """
        UPDATE agent.provider_rate_limits
        SET
            remaining_requests = %s,
            reset_requests_at = %s,
            remaining_tokens = %s,
            reset_tokens_at = %s,
            blocked_until = CASE
                WHEN blocked_until <= %s THEN NULL
                ELSE blocked_until
            END
        WHERE provider = %s AND resource_key = %s
        """,
        (
            remaining_requests,
            reset_requests_at,
            remaining_tokens,
            reset_tokens_at,
            now,
            provider,
            resource_key,
        ),
    )
    return ProviderRateLimitDecision(
        allowed=allowed,
        retry_at=max(retry_candidates) if retry_candidates else None,
        remaining_requests=remaining_requests,
        remaining_tokens=remaining_tokens,
    )


async def observe_provider_rate_limits(
    connection: AsyncConnection[DictRow],
    *,
    provider: str,
    resource_key: str,
    headers: Mapping[str, str],
    request_id: str | None,
    default_rpm: int,
    default_tpm: int,
) -> None:
    """성공·429 응답 헤더로 저장된 상한, 잔여량, Reset·차단 시각을 갱신한다."""
    normalized = {str(key).lower(): str(value) for key, value in headers.items()}
    await connection.execute(
        """
        INSERT INTO agent.provider_rate_limits (
            provider,
            resource_key,
            limit_requests,
            remaining_requests,
            reset_requests_at,
            limit_tokens,
            remaining_tokens,
            reset_tokens_at
        ) VALUES (
            %s, %s, %s, %s, clock_timestamp() + interval '1 minute',
            %s, %s, clock_timestamp() + interval '1 minute'
        )
        ON CONFLICT (provider, resource_key) DO NOTHING
        """,
        (provider, resource_key, default_rpm, default_rpm, default_tpm, default_tpm),
    )
    cursor = await connection.execute(
        """
        SELECT *, clock_timestamp() AS observed_at
        FROM agent.provider_rate_limits
        WHERE provider = %s AND resource_key = %s
        FOR UPDATE
        """,
        (provider, resource_key),
    )
    row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("관찰할 Provider Rate Limit 상태를 찾지 못했습니다.")
    now: datetime = row["observed_at"]
    limit_requests = _positive_header_int(
        normalized, "x-ratelimit-limit-requests"
    ) or int(row["limit_requests"])
    limit_tokens = _positive_header_int(
        normalized, "x-ratelimit-limit-tokens"
    ) or int(row["limit_tokens"])
    observed_requests = _positive_header_int(
        normalized, "x-ratelimit-remaining-requests"
    )
    observed_tokens = _positive_header_int(
        normalized, "x-ratelimit-remaining-tokens"
    )
    remaining_requests = min(
        observed_requests if observed_requests is not None else int(row["remaining_requests"]),
        limit_requests,
    )
    remaining_tokens = min(
        observed_tokens if observed_tokens is not None else int(row["remaining_tokens"]),
        limit_tokens,
    )
    request_reset = parse_rate_limit_reset(
        normalized.get("x-ratelimit-reset-requests")
    )
    token_reset = parse_rate_limit_reset(normalized.get("x-ratelimit-reset-tokens"))
    retry_after = parse_retry_after_seconds(normalized.get("retry-after"))
    await connection.execute(
        """
        UPDATE agent.provider_rate_limits
        SET
            limit_requests = %s,
            remaining_requests = %s,
            reset_requests_at = %s,
            limit_tokens = %s,
            remaining_tokens = %s,
            reset_tokens_at = %s,
            blocked_until = CASE
                WHEN %s::double precision IS NULL THEN blocked_until
                ELSE %s + (%s * interval '1 second')
            END,
            last_request_id = COALESCE(%s, last_request_id),
            metadata = %s
        WHERE provider = %s AND resource_key = %s
        """,
        (
            limit_requests,
            remaining_requests,
            now + request_reset if request_reset is not None else row["reset_requests_at"],
            limit_tokens,
            remaining_tokens,
            now + token_reset if token_reset is not None else row["reset_tokens_at"],
            retry_after,
            now,
            retry_after,
            request_id,
            Jsonb({"headers": normalized}),
            provider,
            resource_key,
        ),
    )
