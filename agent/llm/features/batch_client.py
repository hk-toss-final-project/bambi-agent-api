"""OpenAI Batch JSONL 생성·제출·조회·결과 다운로드 경계."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol, TypeVar

from shared.openai_batch import ProviderBatchSnapshot

from .client import (
    _DEFAULT_MAX_ATTEMPTS,
    _DEFAULT_MAX_RETRY_SECONDS,
    _retry_delay_for_error,
    _transient_error_types,
    is_retryable_openai_error,
)

ResultT = TypeVar("ResultT")


class PreparedBatchItemInput(Protocol):
    """JSONL 직렬화에 필요한 Batch Item 속성 계약."""

    custom_id: str
    request_body: Mapping[str, object]


class PreparedBatchInput(Protocol):
    """Provider 제출에 필요한 로컬 Batch 속성 계약."""

    batch_id: str
    endpoint: str
    workload: str
    items: Sequence[PreparedBatchItemInput]


@dataclass(frozen=True, slots=True)
class ProviderBatchSubmission:
    """OpenAI Batch 제출 직후 받은 Provider 식별자와 상태."""

    provider_batch_id: str
    input_file_id: str
    status: str


class BatchProvider(Protocol):
    """실제 OpenAI와 테스트 대역이 공유하는 Batch Provider 계약."""

    async def submit(self, batch: PreparedBatchInput) -> ProviderBatchSubmission:
        """로컬 Batch JSONL을 업로드하고 Provider Batch를 생성한다."""
        ...

    async def retrieve(self, provider_batch_id: str) -> ProviderBatchSnapshot:
        """Provider Batch의 최신 상태를 조회한다."""
        ...

    async def download_jsonl(self, file_id: str) -> list[dict[str, object]]:
        """Provider 결과 파일을 JSONL 객체 목록으로 읽는다."""
        ...


def build_batch_jsonl(batch: PreparedBatchInput) -> bytes:
    """Batch Item을 custom_id가 포함된 OpenAI 입력 JSONL Byte로 직렬화한다."""
    custom_ids = [item.custom_id for item in batch.items]
    if len(custom_ids) != len(set(custom_ids)):
        raise ValueError("한 OpenAI Batch 안에서 custom_id가 중복됐습니다.")
    lines = [
        json.dumps(
            {
                "custom_id": item.custom_id,
                "method": "POST",
                "url": batch.endpoint,
                "body": item.request_body,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for item in batch.items
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def parse_batch_jsonl(content: bytes | str) -> list[dict[str, object]]:
    """결과 JSONL을 줄별 객체로 파싱하고 손상된 줄 번호를 명확히 알린다."""
    text = content.decode("utf-8") if isinstance(content, bytes) else content
    results: list[dict[str, object]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"OpenAI Batch 결과 JSONL {line_number}번째 줄이 잘못됐습니다."
            ) from error
        if not isinstance(value, dict):
            raise ValueError(
                f"OpenAI Batch 결과 JSONL {line_number}번째 줄은 객체여야 합니다."
            )
        results.append(value)
    return results


def _model_value(value: object) -> object:
    """OpenAI Pydantic Model을 JSON 저장 가능한 값으로 변환한다."""
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return value


async def _call_with_retry(
    operation: Callable[[], Awaitable[ResultT]],
    *,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    max_retry_seconds: float = _DEFAULT_MAX_RETRY_SECONDS,
) -> ResultT:
    """Batch API 호출에 Retry-After 우선 비동기 지수 Backoff를 적용한다."""
    transient = _transient_error_types()
    started = monotonic()
    for attempt in range(1, max_attempts + 1):
        try:
            return await operation()
        except transient as error:
            if attempt >= max_attempts or not is_retryable_openai_error(error):
                raise
            delay = _retry_delay_for_error(error, attempt)
            if monotonic() - started + delay > max_retry_seconds:
                raise
            await asyncio.sleep(delay)
    raise RuntimeError("도달할 수 없는 Batch Provider 재시도 분기입니다.")


class OpenAIBatchProvider:
    """SDK 재시도를 끄고 OpenAI Batch API만 호출하는 Provider 구현."""

    def __init__(self, api_key: str, *, client: Any | None = None) -> None:
        """API Key 또는 테스트용 SDK Client로 Provider를 초기화한다."""
        if client is None:
            if not api_key:
                raise ValueError("OpenAI Batch Provider에 API Key가 필요합니다.")
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, max_retries=0)
        self._client = client

    async def submit(self, batch: PreparedBatchInput) -> ProviderBatchSubmission:
        """입력 JSONL 파일을 올리고 24시간 완료 Window로 Batch를 생성한다."""
        content = build_batch_jsonl(batch)
        input_file = await _call_with_retry(
            lambda: self._client.files.create(
                file=(f"{batch.batch_id}.jsonl", content, "application/jsonl"),
                purpose="batch",
            )
        )
        provider_batch = await _call_with_retry(
            lambda: self._client.batches.create(
                input_file_id=str(input_file.id),
                endpoint=batch.endpoint,
                completion_window="24h",
                metadata={"local_batch_id": batch.batch_id, "workload": batch.workload},
            )
        )
        return ProviderBatchSubmission(
            provider_batch_id=str(provider_batch.id),
            input_file_id=str(input_file.id),
            status=str(provider_batch.status),
        )

    async def retrieve(self, provider_batch_id: str) -> ProviderBatchSnapshot:
        """Provider Batch 상태와 output·error 파일 식별자를 조회한다."""
        batch = await _call_with_retry(
            lambda: self._client.batches.retrieve(provider_batch_id)
        )
        metadata = getattr(batch, "metadata", None)
        return ProviderBatchSnapshot(
            status=str(batch.status),
            input_file_id=(
                str(batch.input_file_id) if getattr(batch, "input_file_id", None) else None
            ),
            output_file_id=(
                str(batch.output_file_id)
                if getattr(batch, "output_file_id", None)
                else None
            ),
            error_file_id=(
                str(batch.error_file_id)
                if getattr(batch, "error_file_id", None)
                else None
            ),
            errors=_model_value(getattr(batch, "errors", None)),
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )

    async def download_jsonl(self, file_id: str) -> list[dict[str, object]]:
        """OpenAI 파일 내용을 읽어 JSONL 결과 객체로 반환한다."""
        response = await _call_with_retry(lambda: self._client.files.content(file_id))
        content = await _call_with_retry(response.aread)
        return parse_batch_jsonl(content)
