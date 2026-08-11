"""OpenAI Batch Worker의 외부 호출·DB 상태 변경 경계를 검증한다."""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any

import pytest

from agent.llm.api import ProviderBatchSubmission
from infrastructure.persistence.api import (
    DueLlmBatch,
    PreparedLlmBatch,
    PreparedLlmBatchItem,
    ProviderBatchSnapshot,
)
from workers.features import openai_batch


class _FakeConnection:
    """빈 Transaction 문맥을 제공하는 연결 대역."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """상태 변경 Transaction 구간을 흉내 낸다."""
        yield


class _TrackingPool:
    """현재 대여 중인 DB 연결 수를 기록하는 Pool 대역."""

    def __init__(self) -> None:
        """활성 연결 수를 0으로 초기화한다."""
        self.active = 0

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_FakeConnection]:
        """문맥 안에서 활성 연결 수를 증감한다."""
        self.active += 1
        try:
            yield _FakeConnection()
        finally:
            self.active -= 1


def _prepared_batch() -> PreparedLlmBatch:
    """제출 Worker 테스트용 로컬 Batch를 만든다."""
    return PreparedLlmBatch(
        batch_id="batch-local-1",
        provider="openai",
        endpoint="/v1/embeddings",
        model_name="text-embedding-3-small",
        workload="wiki_embedding",
        items=(
            PreparedLlmBatchItem(
                item_id="item-1",
                custom_id="wiki:1",
                request_body={"input": ["본문"]},
            ),
        ),
    )


class _Provider:
    """호출 시 DB 연결이 반환됐는지 검증하는 Provider 대역."""

    def __init__(self, pool: _TrackingPool) -> None:
        """검증할 Pool을 저장한다."""
        self.pool = pool
        self.downloaded: list[str] = []

    async def submit(self, batch: PreparedLlmBatch) -> ProviderBatchSubmission:
        """DB 연결이 없는 상태에서 고정 제출 결과를 반환한다."""
        assert self.pool.active == 0
        return ProviderBatchSubmission(
            provider_batch_id="batch-provider-1",
            input_file_id="file-input-1",
            status="validating",
        )

    async def retrieve(self, provider_batch_id: str) -> ProviderBatchSnapshot:
        """DB 연결이 없는 상태에서 완료 Snapshot을 반환한다."""
        assert self.pool.active == 0
        return ProviderBatchSnapshot(
            status="completed",
            output_file_id="file-output-1",
            error_file_id="file-error-1",
        )

    async def download_jsonl(self, file_id: str) -> list[dict[str, object]]:
        """output·error 파일 다운로드 순서를 기록한다."""
        assert self.pool.active == 0
        self.downloaded.append(file_id)
        return [{"custom_id": file_id}]


def test_submit_batch_releases_connection_during_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSONL 업로드와 Batch 생성 중 PostgreSQL 연결을 점유하지 않는다."""
    pool = _TrackingPool()
    provider = _Provider(pool)
    marked: dict[str, Any] = {}

    async def fake_claim(pool_value: Any, **kwargs: Any) -> PreparedLlmBatch:
        """고정 로컬 Batch를 반환한다."""
        return _prepared_batch()

    async def fake_scope(connection: Any) -> None:
        """시스템 Scope SQL을 생략한다."""

    async def fake_mark(connection: Any, **kwargs: Any) -> None:
        """제출 상태 저장 인자를 기록한다."""
        marked.update(kwargs)

    monkeypatch.setattr(openai_batch, "_claim_submission", fake_claim)
    monkeypatch.setattr(openai_batch, "set_system_job_scope", fake_scope)
    monkeypatch.setattr(openai_batch, "mark_llm_batch_submitted", fake_mark)

    result = asyncio.run(
        openai_batch._submit_batch(  # type: ignore[arg-type]
            pool,
            provider=provider,
            max_items=500,
            poll_interval_seconds=60,
        )
    )

    assert result is not None and result["status"] == "validating"
    assert marked["provider_batch_id"] == "batch-provider-1"
    assert pool.active == 0


def test_poll_batch_downloads_output_and_error_before_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """부분 성공을 위해 두 결과 파일을 받고 난 뒤 한 Transaction으로 반영한다."""
    pool = _TrackingPool()
    provider = _Provider(pool)
    applied: dict[str, Any] = {}

    async def fake_scope(connection: Any) -> None:
        """시스템 Scope SQL을 생략한다."""

    async def fake_update(connection: Any, **kwargs: Any) -> None:
        """Provider Snapshot 저장을 생략한다."""

    async def fake_apply(connection: Any, **kwargs: Any) -> dict[str, int]:
        """합쳐진 결과 줄을 기록하고 집계값을 반환한다."""
        applied.update(kwargs)
        return {"completed": 1, "failed": 1, "requeued": 0}

    monkeypatch.setattr(openai_batch, "set_system_job_scope", fake_scope)
    monkeypatch.setattr(openai_batch, "update_llm_batch_snapshot", fake_update)
    monkeypatch.setattr(openai_batch, "apply_llm_batch_result_lines", fake_apply)
    due = DueLlmBatch(
        batch_id="batch-local-1",
        provider_batch_id="batch-provider-1",
        endpoint="/v1/embeddings",
        model_name="text-embedding-3-small",
        workload="wiki_embedding",
    )

    result = asyncio.run(
        openai_batch._poll_batch(  # type: ignore[arg-type]
            pool,
            provider=provider,
            batch=due,
            poll_interval_seconds=60,
        )
    )

    assert provider.downloaded == ["file-output-1", "file-error-1"]
    assert len(applied["lines"]) == 2
    assert result["completed"] == 1
    assert result["failed"] == 1
    assert pool.active == 0
