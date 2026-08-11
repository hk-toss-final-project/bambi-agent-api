"""Worker Job 재시도 적용 기능과 Backoff·DLQ Scaffold."""

from typing import Any

from psycopg import AsyncConnection

from infrastructure.persistence.api import (
    ClaimedAgentJob,
    FailAgentJobCommand,
    db_026,
)
from shared.retry import exponential_backoff_delay
from shared.contracts import FeatureRequest, FeatureResult


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wc_006(
    connection: AsyncConnection[dict[str, Any]],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    error_code: str,
    error_message: str,
    retryable: bool,
    retry_delay_seconds: float | None = None,
) -> str:
    """[WC-006] Retry 정책.

    재시도 가능한 오류에 재처리 정책을 적용한다.
    """
    result = await db_026(
        connection,
        FailAgentJobCommand(
            job=job,
            worker_id=worker_id,
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
            retry_delay_seconds=retry_delay_seconds,
        ),
    )
    if not isinstance(result, str):
        raise RuntimeError("DB-026이 Job 실패 후 상태를 반환하지 않았습니다.")
    return result


async def wc_007(
    attempt: int,
    *,
    retry_after_seconds: float | None = None,
    base_seconds: float = 1.0,
    max_backoff_seconds: float = 300.0,
    jitter_ratio: float = 0.25,
) -> float:
    """[WC-007] Exponential Backoff.

    Retry-After를 최소값으로 존중하면서 재시도 간격을 점진적으로 증가시킨다.
    """
    return exponential_backoff_delay(
        attempt,
        retry_after_seconds=retry_after_seconds,
        base_seconds=base_seconds,
        max_backoff_seconds=max_backoff_seconds,
        jitter_ratio=jitter_ratio,
    )


async def wc_008(request: FeatureRequest) -> FeatureResult:
    """[WC-008] Dead Letter Queue.

    반복 실패 작업을 격리한다.
    """
    raise NotImplementedError("[WC-008] 기능 구현이 필요합니다.")
