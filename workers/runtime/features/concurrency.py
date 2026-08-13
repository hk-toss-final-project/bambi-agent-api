"""Worker Job 동시 실행 제어와 외부 API Rate Limit 기능."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection

from infrastructure.persistence.api import (
    ProviderRateLimitDecision,
    reserve_provider_capacity,
)

type DictRow = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderRateLimitPolicy:
    """Worker가 예약할 OpenAI 모델별 예상 RPM·TPM 용량 정책."""

    provider: str
    resource_key: str
    estimated_requests: int
    estimated_tokens: int
    default_rpm: int
    default_tpm: int
    max_wait_slice_seconds: float = 30.0


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wc_013[ItemT, ResultT](
    items: Sequence[ItemT],
    processor: Callable[[ItemT], Awaitable[ResultT]],
    *,
    max_concurrency: int = 1,
) -> list[ResultT]:
    """[WC-013] Concurrency 제어.

    작업 유형별 동시 실행 수를 제한한다.
    """
    if max_concurrency < 1:
        raise ValueError("WC-013 max_concurrency는 1 이상이어야 합니다.")
    semaphore = asyncio.Semaphore(max_concurrency)

    async def run(item: ItemT) -> ResultT:
        """Semaphore 안에서 Item 하나를 실행한다."""
        async with semaphore:
            return await processor(item)

    return list(await asyncio.gather(*(run(item) for item in items)))


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wc_014(
    connection: AsyncConnection[DictRow],
    *,
    policy: ProviderRateLimitPolicy,
) -> ProviderRateLimitDecision:
    """[WC-014] 외부 API Rate Limit.

    PostgreSQL의 모델별 공유 상태에서 예상 요청·Token 용량을 예약한다.
    """
    return await reserve_provider_capacity(
        connection,
        provider=policy.provider,
        resource_key=policy.resource_key,
        request_count=policy.estimated_requests,
        estimated_tokens=policy.estimated_tokens,
        default_rpm=policy.default_rpm,
        default_tpm=policy.default_tpm,
    )
