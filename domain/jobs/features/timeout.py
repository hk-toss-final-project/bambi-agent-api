"""Agent Job Lease 타임아웃 판정 기능 구현."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AgentJobLeaseSnapshot:
    """Lease 타임아웃 판정에 필요한 Agent Job 상태 스냅샷."""

    status: str
    attempt_count: int
    max_attempts: int
    lease_expires_at: datetime | None


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def job_009(job: AgentJobLeaseSnapshot, *, now: datetime) -> bool:
    """[JOB-009] Agent Job Timeout.

    작업별 최대 실행 시간을 적용한다.

    claim_runnable_agent_jobs는 attempt_count < max_attempts인 Job만 다시
    집으므로, 마지막 시도의 Worker가 죽거나 Heartbeat 연장에 실패해 Lease가
    만료된 채 시도를 다 쓴 running Job은 그 뒤로 아무도 회수하지 못하고
    영구히 running으로 남는다. 이 판정이 그런 Job을 찾아 강제 종료(failed)
    대상으로 표시한다.
    """
    if job.status != "running":
        return False
    if job.lease_expires_at is None or job.lease_expires_at >= now:
        return False
    return job.attempt_count >= job.max_attempts
