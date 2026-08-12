"""WC-003 Worker heartbeat의 저장 경계 위임을 검증한다."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from infrastructure.persistence.api import ClaimedAgentJob
from workers.runtime.features import heartbeat


def _job() -> ClaimedAgentJob:
    """heartbeat 테스트용 실행 중 Job을 만든다."""
    return ClaimedAgentJob(
        job_id="job-1",
        user_id="user-1",
        feature_id="SVC-008",
        job_type="report_generation",
        attempt_number=2,
        max_attempts=3,
    )


def test_wc_003_extends_the_claimed_job_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WC-003이 현재 Job·Worker·Lease 길이를 영속화 경계에 그대로 전달한다."""
    expected = datetime(2026, 8, 11, 12, 10, tzinfo=UTC)
    captured: dict[str, Any] = {}

    async def fake_extend(connection: Any, **kwargs: Any) -> datetime:
        """Lease 연장 인자를 기록하고 고정 만료 시각을 반환한다."""
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(heartbeat, "extend_agent_job_lease", fake_extend)
    job = _job()
    connection = object()

    result = asyncio.run(
        heartbeat.wc_003(
            connection,  # type: ignore[arg-type]
            job=job,
            worker_id="worker-1",
            lease_seconds=600,
        )
    )

    assert result == expected
    assert captured == {
        "job": job,
        "worker_id": "worker-1",
        "lease_seconds": 600,
    }
