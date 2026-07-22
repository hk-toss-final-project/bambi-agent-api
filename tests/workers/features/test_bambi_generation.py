"""Bambi Generation Worker의 러너 위임과 입력 검증을 검증한다."""

import asyncio
from typing import Any

import pytest

from workers.features import bambi_generation
from workers.features.bambi_generation import worker_003


def test_run_bambi_generation_batch_delegates_to_shared_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """생성 Batch가 공통 러너에 유형·오류 접두사·처리 함수를 전달한다."""
    captured: dict[str, Any] = {}

    async def fake_run_job_batch(**kwargs: Any) -> list[dict[str, object]]:
        """공통 Batch 러너 호출 인자를 기록하고 고정 결과를 반환한다."""
        captured.update(kwargs)
        return [{"job_id": "bambi-job-1", "status": "completed"}]

    monkeypatch.setattr(bambi_generation, "run_job_batch", fake_run_job_batch)

    results = asyncio.run(
        bambi_generation.run_bambi_generation_batch(
            database_url="postgresql://test",
            worker_id="worker-1",
            limit=3,
            lease_seconds=600,
            model="bambi-model",
        )
    )

    assert results == [{"job_id": "bambi-job-1", "status": "completed"}]
    assert captured["job_type"] == "bambi_generation"
    assert captured["error_code_prefix"] == "BAMBI_GENERATION"
    assert captured["limit"] == 3
    assert callable(captured["process"])


def test_worker_003_requires_database_url() -> None:
    """WORKER-003이 DB 연결 없이 호출되면 명확한 검증 오류를 낸다."""
    with pytest.raises(ValueError, match="database_url"):
        asyncio.run(worker_003(database_url="", worker_id="worker-1"))
