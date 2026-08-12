"""Agent Job Lease 타임아웃 판정(JOB-009)의 typed 계약을 검증한다."""

import asyncio
from datetime import UTC, datetime

from domain.jobs.features.timeout import AgentJobLeaseSnapshot, job_009

_NOW = datetime(2026, 8, 12, 5, 0, tzinfo=UTC)


def _snapshot(**overrides: object) -> AgentJobLeaseSnapshot:
    """기본값이 회수 대상인 Lease 스냅샷을 만든다."""
    values: dict[str, object] = {
        "status": "running",
        "attempt_count": 3,
        "max_attempts": 3,
        "lease_expires_at": datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return AgentJobLeaseSnapshot(**values)  # type: ignore[arg-type]


def test_job_009_reaps_running_job_with_exhausted_attempts_and_expired_lease() -> None:
    """시도를 다 쓴 채 Lease가 지난 running Job을 회수 대상으로 판정한다."""
    assert asyncio.run(job_009(_snapshot(), now=_NOW)) is True


def test_job_009_ignores_jobs_that_are_not_running() -> None:
    """queued·completed·failed 등 running이 아닌 Job은 대상에서 제외한다."""
    for status in ("queued", "completed", "failed", "waiting_provider"):
        assert asyncio.run(job_009(_snapshot(status=status), now=_NOW)) is False


def test_job_009_ignores_jobs_whose_lease_has_not_expired_yet() -> None:
    """Lease가 아직 살아 있으면 회수 대상이 아니다."""
    future_lease = datetime(2026, 8, 12, 6, 0, tzinfo=UTC)
    assert (
        asyncio.run(job_009(_snapshot(lease_expires_at=future_lease), now=_NOW))
        is False
    )


def test_job_009_ignores_jobs_without_a_lease() -> None:
    """Lease가 아예 없는 Job(claim 이전 상태)은 회수 대상이 아니다."""
    assert (
        asyncio.run(job_009(_snapshot(lease_expires_at=None), now=_NOW)) is False
    )


def test_job_009_ignores_jobs_with_remaining_attempts() -> None:
    """Lease는 지났지만 아직 재시도 여지가 있으면 claim_runnable_agent_jobs가 다시 집으므로 회수 대상이 아니다."""
    assert (
        asyncio.run(
            job_009(_snapshot(attempt_count=1, max_attempts=3), now=_NOW)
        )
        is False
    )
