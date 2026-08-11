"""OpenAI Batch JSONL과 SDK 경계를 실제 API 호출 없이 검증한다."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from agent.llm.features.batch_client import (
    OpenAIBatchProvider,
    _call_with_retry,
    build_batch_jsonl,
    parse_batch_jsonl,
)
from agent.llm.features import batch_client
from infrastructure.persistence.api import PreparedLlmBatch, PreparedLlmBatchItem


def _batch() -> PreparedLlmBatch:
    """서로 다른 custom_id를 가진 Embedding Batch 예시를 만든다."""
    return PreparedLlmBatch(
        batch_id="batch-local-1",
        provider="openai",
        endpoint="/v1/embeddings",
        model_name="text-embedding-3-small",
        workload="wiki_embedding",
        items=(
            PreparedLlmBatchItem(
                item_id="item-1",
                custom_id="wiki:2",
                request_body={"model": "text-embedding-3-small", "input": ["둘"]},
            ),
            PreparedLlmBatchItem(
                item_id="item-2",
                custom_id="wiki:1",
                request_body={"model": "text-embedding-3-small", "input": ["하나"]},
            ),
        ),
    )


def test_build_batch_jsonl_preserves_custom_id_and_endpoint() -> None:
    """입력 순서와 무관한 재결합 Key·endpoint·Body가 각 JSONL 줄에 들어간다."""
    lines = build_batch_jsonl(_batch()).decode("utf-8").splitlines()
    values = [json.loads(line) for line in lines]

    assert [value["custom_id"] for value in values] == ["wiki:2", "wiki:1"]
    assert all(value["method"] == "POST" for value in values)
    assert all(value["url"] == "/v1/embeddings" for value in values)
    assert values[0]["body"]["input"] == ["둘"]


def test_build_batch_jsonl_rejects_duplicate_custom_id() -> None:
    """한 파일 안의 custom_id 중복은 Provider 제출 전에 차단한다."""
    item = _batch().items[0]
    duplicate = PreparedLlmBatch(
        batch_id="batch-local-2",
        provider="openai",
        endpoint="/v1/embeddings",
        model_name="text-embedding-3-small",
        workload="wiki_embedding",
        items=(item, item),
    )

    with pytest.raises(ValueError, match="custom_id"):
        build_batch_jsonl(duplicate)


def test_parse_batch_jsonl_keeps_out_of_order_results() -> None:
    """결과 순서를 가정하지 않고 각 JSON 객체를 그대로 반환한다."""
    content = '{"custom_id":"wiki:2"}\n{"custom_id":"wiki:1"}\n'

    assert [line["custom_id"] for line in parse_batch_jsonl(content)] == [
        "wiki:2",
        "wiki:1",
    ]


class _FakeFiles:
    """업로드 인자를 기록하고 결과 파일 Byte를 반환하는 SDK 대역."""

    def __init__(self) -> None:
        """빈 업로드 기록을 초기화한다."""
        self.created: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        """파일 생성 인자를 기록하고 고정 ID를 반환한다."""
        self.created = kwargs
        return SimpleNamespace(id="file-input-1")

    async def content(self, file_id: str) -> Any:
        """비동기 aread를 제공하는 결과 응답을 반환한다."""
        async def aread() -> bytes:
            """고정 결과 JSONL Byte를 반환한다."""
            return b'{"custom_id":"wiki:1"}\n'

        return SimpleNamespace(aread=aread)


class _FakeBatches:
    """Batch 생성·조회 인자를 기록하는 SDK 대역."""

    def __init__(self) -> None:
        """빈 생성 기록을 초기화한다."""
        self.created: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        """생성 인자를 기록하고 submitted Batch를 반환한다."""
        self.created = kwargs
        return SimpleNamespace(id="batch-provider-1", status="validating")

    async def retrieve(self, batch_id: str) -> Any:
        """완료 상태와 결과 파일 ID를 반환한다."""
        return SimpleNamespace(
            id=batch_id,
            status="completed",
            input_file_id="file-input-1",
            output_file_id="file-output-1",
            error_file_id=None,
            errors=None,
            metadata={"local_batch_id": "batch-local-1"},
        )


def test_openai_batch_provider_submits_24_hour_batch() -> None:
    """SDK 경계가 batch purpose 파일과 24h 완료 Window를 사용한다."""
    client = SimpleNamespace(files=_FakeFiles(), batches=_FakeBatches())
    provider = OpenAIBatchProvider("", client=client)

    submission = asyncio.run(provider.submit(_batch()))
    snapshot = asyncio.run(provider.retrieve(submission.provider_batch_id))
    output = asyncio.run(provider.download_jsonl("file-output-1"))

    assert submission.provider_batch_id == "batch-provider-1"
    assert client.files.created["purpose"] == "batch"
    assert client.batches.created["completion_window"] == "24h"
    assert client.batches.created["endpoint"] == "/v1/embeddings"
    assert snapshot.status == "completed"
    assert output == [{"custom_id": "wiki:1"}]


class _TransientError(RuntimeError):
    """Batch 비동기 재시도 테스트용 일시 오류."""


class _QuotaError(RuntimeError):
    """재시도하면 안 되는 Batch 사용량 한도 오류."""

    code = "insufficient_quota"


def test_batch_call_retries_with_async_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch 일시 오류는 비동기 Backoff 후 제한된 횟수 안에서 재시도한다."""
    calls = 0
    sleeps: list[float] = []

    async def operation() -> str:
        """첫 호출은 실패하고 두 번째 호출은 성공한다."""
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _TransientError("429")
        return "ok"

    async def fake_sleep(delay: float) -> None:
        """실제 대기 없이 계산된 Backoff를 기록한다."""
        sleeps.append(delay)

    monkeypatch.setattr(
        batch_client,
        "_transient_error_types",
        lambda: (_TransientError,),
    )
    monkeypatch.setattr(
        batch_client,
        "_retry_delay_for_error",
        lambda error, attempt: 2.5,
    )
    monkeypatch.setattr(batch_client.asyncio, "sleep", fake_sleep)

    result = asyncio.run(_call_with_retry(operation))

    assert result == "ok"
    assert calls == 2
    assert sleeps == [2.5]


def test_batch_call_does_not_retry_quota_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """사용자 조치가 필요한 quota 오류는 Batch에서도 즉시 전파한다."""
    calls = 0

    async def operation() -> str:
        """호출 횟수를 기록하고 quota 오류를 발생시킨다."""
        nonlocal calls
        calls += 1
        raise _QuotaError("quota")

    monkeypatch.setattr(
        batch_client,
        "_transient_error_types",
        lambda: (_QuotaError,),
    )

    with pytest.raises(_QuotaError):
        asyncio.run(_call_with_retry(operation))

    assert calls == 1
