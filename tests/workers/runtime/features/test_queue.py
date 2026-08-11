"""WC-001 Queue Job Consume 루프를 검증한다."""

import asyncio
from typing import Any

import pytest

from workers.runtime.features import queue
from workers.runtime.features.queue import (
    consume_briefing_preparation_jobs,
    consume_report_generation_jobs,
    consume_personal_wiki_jobs,
    consume_url_collection_jobs,
    wc_001,
)


class _FakeBatchRunner:
    """호출 순서별로 고정된 Batch 결과를 돌려주는 실행기 Test Double."""

    def __init__(self, batches: list[list[dict[str, object]]]) -> None:
        """순서별 Batch 결과와 빈 호출 내역을 초기화한다."""
        self._batches = batches
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> list[dict[str, object]]:
        """호출 인자를 기록하고 다음 Batch 결과를 반환한다."""
        self.calls.append(kwargs)
        return self._batches.pop(0) if self._batches else []


def test_consume_drains_available_batches_up_to_max_batches() -> None:
    """결과가 있는 Batch는 즉시 이어서 소비하고 상한에서 멈춘다."""
    runner = _FakeBatchRunner(
        [
            [{"job_id": "job-1", "status": "completed"}],
            [{"job_id": "job-2", "status": "completed"}],
            [],
        ]
    )
    observed: list[list[dict[str, object]]] = []

    results = asyncio.run(
        consume_personal_wiki_jobs(
            database_url="postgresql://test",
            worker_id="worker-1",
            limit=5,
            lease_seconds=600,
            model="gpt-4.1-mini",
            interval_seconds=0,
            max_batches=3,
            batch_runner=runner,
            on_batch=observed.append,
        )
    )

    assert [result["job_id"] for result in results] == ["job-1", "job-2"]
    assert len(runner.calls) == 3
    assert runner.calls[0]["limit"] == 5
    assert runner.calls[0]["worker_id"] == "worker-1"
    assert observed == [
        [{"job_id": "job-1", "status": "completed"}],
        [{"job_id": "job-2", "status": "completed"}],
    ]


def test_consume_report_generation_jobs_passes_generation_arguments() -> None:
    """Report Builder 소비 루프가 생성 Batch 실행기에 생성 인자만 전달한다."""
    runner = _FakeBatchRunner([[{"job_id": "report-job-1", "status": "completed"}]])

    results = asyncio.run(
        consume_report_generation_jobs(
            database_url="postgresql://test",
            worker_id="report-worker-1",
            limit=3,
            lease_seconds=600,
            model="gpt-4.1-mini",
            interval_seconds=0,
            max_batches=1,
            batch_runner=runner,
        )
    )

    assert [result["job_id"] for result in results] == ["report-job-1"]
    assert runner.calls[0]["worker_id"] == "report-worker-1"
    assert runner.calls[0]["model"] == "gpt-4.1-mini"
    assert "embedding_model" not in runner.calls[0]


def test_consume_briefing_preparation_jobs_passes_bounded_concurrency() -> None:
    """브리핑 준비 소비 루프가 Batch 크기와 실제 동시성을 따로 전달한다."""
    runner = _FakeBatchRunner(
        [[{"job_id": "briefing-job-1", "status": "completed"}]]
    )

    results = asyncio.run(
        consume_briefing_preparation_jobs(
            database_url="postgresql://test",
            worker_id="briefing-worker-1",
            limit=8,
            concurrency=2,
            lease_seconds=600,
            model="gpt-4.1-mini",
            interval_seconds=0,
            max_batches=1,
            batch_runner=runner,
        )
    )

    assert [result["job_id"] for result in results] == ["briefing-job-1"]
    assert runner.calls[0]["limit"] == 8
    assert runner.calls[0]["concurrency"] == 2


def test_wc_001_routes_briefing_preparation_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WC-001이 브리핑 준비 유형을 전용 소비 루프로 전달한다."""
    recorded: dict[str, Any] = {}

    async def fake_consume(**kwargs: Any) -> list[dict[str, object]]:
        """전용 소비기 인자를 기록한다."""
        recorded.update(kwargs)
        return [{"job_id": "briefing-job-1", "status": "completed"}]

    monkeypatch.setattr(queue, "consume_briefing_preparation_jobs", fake_consume)

    results = asyncio.run(
        wc_001(
            database_url="postgresql://test",
            worker_id="briefing-worker-1",
            limit=8,
            concurrency=2,
            lease_seconds=600,
            model="gpt-4.1-mini",
            interval_seconds=5,
            max_batches=1,
            job_type="briefing_preparation",
        )
    )

    assert results[0]["job_id"] == "briefing-job-1"
    assert recorded["concurrency"] == 2


def test_consume_url_collection_jobs_passes_no_llm_model() -> None:
    """URL 수집 소비 루프가 Jina Batch 실행기에 DB·Lease 인자만 전달한다."""
    runner = _FakeBatchRunner([[{"job_id": "url-job-1", "status": "completed"}]])

    results = asyncio.run(
        consume_url_collection_jobs(
            database_url="postgresql://test",
            worker_id="url-worker-1",
            limit=4,
            lease_seconds=120,
            interval_seconds=0,
            max_batches=1,
            batch_runner=runner,
        )
    )

    assert [result["job_id"] for result in results] == ["url-job-1"]
    assert runner.calls[0] == {
        "database_url": "postgresql://test",
        "worker_id": "url-worker-1",
        "limit": 4,
        "lease_seconds": 120,
    }


def test_wc_001_routes_url_job_type_to_collection_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WC-001이 LLM 모델 없이 personal_wiki_url 상주 소비기를 선택하는지 검증한다."""
    recorded: dict[str, Any] = {}

    async def fake_consume(**kwargs: Any) -> list[dict[str, object]]:
        """URL 소비기 인자를 기록한다."""
        recorded.update(kwargs)
        return [{"job_id": "url-job-1", "status": "completed"}]

    monkeypatch.setattr(queue, "consume_url_collection_jobs", fake_consume)

    results = asyncio.run(
        wc_001(
            database_url="postgresql://test",
            worker_id="url-worker-1",
            limit=3,
            lease_seconds=120,
            model="",
            interval_seconds=5,
            max_batches=1,
            job_type="personal_wiki_url",
        )
    )

    assert results[0]["job_id"] == "url-job-1"
    assert recorded["interval_seconds"] == 5
    assert recorded["max_batches"] == 1


def test_consume_returns_empty_when_no_jobs_are_claimable() -> None:
    """실행 가능한 Job이 없으면 빈 결과로 종료한다."""
    runner = _FakeBatchRunner([[]])

    results = asyncio.run(
        consume_personal_wiki_jobs(
            database_url="postgresql://test",
            worker_id="worker-1",
            limit=5,
            lease_seconds=600,
            model="gpt-4.1-mini",
            interval_seconds=0,
            max_batches=1,
            batch_runner=runner,
        )
    )

    assert results == []
    assert len(runner.calls) == 1


def test_consume_validates_loop_settings() -> None:
    """max_batches와 interval_seconds 제약을 실행 전에 검증한다."""
    runner = _FakeBatchRunner([])

    with pytest.raises(ValueError, match="max_batches"):
        asyncio.run(
            consume_personal_wiki_jobs(
                database_url="postgresql://test",
                worker_id="worker-1",
                limit=5,
                lease_seconds=600,
                model="gpt-4.1-mini",
                max_batches=0,
                batch_runner=runner,
            )
        )
    with pytest.raises(ValueError, match="interval_seconds"):
        asyncio.run(
            consume_personal_wiki_jobs(
                database_url="postgresql://test",
                worker_id="worker-1",
                limit=5,
                lease_seconds=600,
                model="gpt-4.1-mini",
                interval_seconds=-1,
                max_batches=1,
                batch_runner=runner,
            )
        )


class _FlakyBatchRunner:
    """첫 호출은 예외를 던지고 이후에는 고정 결과를 반환하는 Test Double."""

    def __init__(self, batches: list[list[dict[str, object]]]) -> None:
        """실패 후 반환할 Batch와 호출 횟수를 초기화한다."""
        self._batches = batches
        self.calls = 0

    async def __call__(self, **kwargs: object) -> list[dict[str, object]]:
        """첫 호출에서 실패한 뒤 다음 Batch 결과를 반환한다."""
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("Job Lease 소유권이 없습니다: job-1")
        return self._batches.pop(0) if self._batches else []


def test_consume_survives_batch_runner_exception() -> None:
    """Batch 하나의 예외가 상주 소비 루프를 죽이지 않는다."""
    runner = _FlakyBatchRunner([[{"job_id": "job-2", "status": "completed"}]])

    results = asyncio.run(
        consume_personal_wiki_jobs(
            database_url="postgresql://test",
            worker_id="worker-1",
            limit=5,
            lease_seconds=600,
            model="gpt-4.1-mini",
            interval_seconds=0,
            max_batches=2,
            batch_runner=runner,
        )
    )

    assert runner.calls == 2
    assert [result["job_id"] for result in results] == ["job-2"]


def test_wc_001_requires_database_url() -> None:
    """WC-001 기능 함수가 database_url 없이 실행되지 않는다."""
    with pytest.raises(ValueError, match="database_url"):
        asyncio.run(
            wc_001(
                database_url="",
                worker_id="worker-1",
            )
        )
