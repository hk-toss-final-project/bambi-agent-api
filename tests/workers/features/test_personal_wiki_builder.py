"""Personal Wiki Builder Worker의 공통 러너 위임을 검증한다."""

import asyncio
from typing import Any

import pytest

from workers.features import personal_wiki_builder


def test_run_personal_wiki_batch_delegates_to_shared_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wiki Batch가 공통 러너에 유형·오류 접두사·처리 함수를 전달한다."""
    captured: dict[str, Any] = {}

    async def fake_run_job_batch(**kwargs: Any) -> list[dict[str, object]]:
        captured.update(kwargs)
        return [{"job_id": "job-1", "status": "completed"}]

    monkeypatch.setattr(
        personal_wiki_builder, "run_job_batch", fake_run_job_batch
    )

    results = asyncio.run(
        personal_wiki_builder.run_personal_wiki_batch(
            database_url="postgresql://test",
            worker_id="worker-1",
            limit=5,
            lease_seconds=600,
            model="wiki-model",
        )
    )

    assert results == [{"job_id": "job-1", "status": "completed"}]
    assert captured["job_type"] == "personal_wiki_build"
    assert captured["error_code_prefix"] == "WIKI_BUILD"
    assert captured["worker_id"] == "worker-1"
    assert callable(captured["process"])
    assert captured["serialization_key"](
        type("Job", (), {"user_id": "user-1"})()
    ) == "personal_wiki_build:user-1"
