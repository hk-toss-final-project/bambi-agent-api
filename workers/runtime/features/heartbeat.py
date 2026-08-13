"""Worker Job Lease heartbeat 기능.

WC-003은 실행 중인 Job의 현재 Attempt 소유권을 확인해 Lease를 연장한다.
"""

from datetime import datetime
from typing import Any

from psycopg import AsyncConnection

from infrastructure.persistence.api import ClaimedAgentJob, extend_agent_job_lease


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wc_003(
    connection: AsyncConnection[dict[str, Any]],
    *,
    job: ClaimedAgentJob,
    worker_id: str,
    lease_seconds: int,
) -> datetime | None:
    """[WC-003] Worker Heartbeat.

    현재 Worker와 Attempt가 소유한 실행 중 Job의 Claim Lease를 연장한다.
    같은 Attempt가 이미 완료됐다면 None을 반환해 heartbeat를 정상 종료한다.
    """
    return await extend_agent_job_lease(
        connection,
        job=job,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )
