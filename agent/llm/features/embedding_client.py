"""공유 Embedding 호출 경계.

OpenAI Embedding 클라이언트 생성·캐시를 한 곳에 모아, 도메인별로 설정
(dimensions)이 어긋난 클라이언트가 중복 생성되지 않게 한다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from .client import (
    _DEFAULT_MAX_ATTEMPTS,
    _DEFAULT_MAX_RETRY_SECONDS,
    _DEFAULT_TIMEOUT_SECONDS,
    _call_with_retry,
    _provider_error_code,
    provider_http_status,
    record_llm_call_observation,
)


class EmbeddingClient(Protocol):
    """문자열 목록을 Vector 목록으로 변환하는 Client 계약."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """입력 문자열과 같은 순서의 Embedding Vector를 반환한다."""
        ...


@dataclass(frozen=True, slots=True)
class _EmbeddingCallResult:
    """OpenAI Embedding Vector와 사용량·응답 Metadata."""

    vectors: list[list[float]]
    input_tokens: int
    response_metadata: Mapping[str, object]


class _RetryingEmbeddingClient:
    """SDK 내부 재시도를 끄고 공통 Backoff를 적용하는 Embedding Client."""

    def __init__(
        self,
        model: str,
        embed: Callable[[list[str]], _EmbeddingCallResult],
    ) -> None:
        """모델 이름과 실제 SDK Embedding 호출 함수를 보관한다."""
        self._model = model
        self._embed = embed

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """각 Provider 시도를 관찰하며 문자열 목록을 Embedding한다."""
        logical_call_id = str(uuid4())

        def observe_attempt(
            attempt: int,
            latency_ms: int,
            value: object | None,
            error: Exception | None,
        ) -> None:
            """Embedding 한 시도의 성공·실패와 실제 입력 Token을 수집한다."""
            observed = value if error is None else error
            if observed is None:
                return
            input_tokens = (
                value.input_tokens
                if isinstance(value, _EmbeddingCallResult)
                else 0
            )
            record_llm_call_observation(
                model=self._model,
                input_tokens=input_tokens,
                output_tokens=0,
                value=observed,
                operation="embedding",
                status="succeeded" if error is None else "failed",
                latency_ms=latency_ms,
                logical_call_id=logical_call_id,
                attempt_number=attempt,
                error_code=(
                    _provider_error_code(error) or None
                    if error is not None
                    else None
                ),
                http_status=provider_http_status(observed),
                metadata={"input_count": len(texts)},
            )

        result = _call_with_retry(
            lambda: self._embed(texts),
            max_attempts=_DEFAULT_MAX_ATTEMPTS,
            max_retry_seconds=_DEFAULT_MAX_RETRY_SECONDS,
            on_attempt=observe_attempt,
        )
        return result.vectors


def _create_openai_embedding_call(
    client: object,
    texts: list[str],
    *,
    model: str,
    dimensions: int | None,
) -> _EmbeddingCallResult:
    """OpenAI 원시 응답에서 순서가 보장된 Vector와 실제 Token을 추출한다."""
    embeddings = getattr(client, "embeddings")
    raw_resource = getattr(embeddings, "with_raw_response")
    options: dict[str, object] = {"input": texts, "model": model}
    if dimensions is not None:
        options["dimensions"] = dimensions
    raw_response = raw_resource.create(**options)
    response = raw_response.parse()
    data = sorted(response.data, key=lambda item: int(item.index))
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    headers = getattr(raw_response, "headers", None)
    return _EmbeddingCallResult(
        vectors=[list(item.embedding) for item in data],
        input_tokens=input_tokens,
        response_metadata={
            "headers": dict(headers) if isinstance(headers, Mapping) else {},
            "model_name": str(getattr(response, "model", model)),
        },
    )


# (model, dimensions) 조합별로 클라이언트를 한 번만 생성해 재사용한다.
_clients: dict[tuple[str, int | None], EmbeddingClient] = {}


def get_embedding_client(
    model: str, *, dimensions: int | None = None
) -> EmbeddingClient:
    """설정 조합에 해당하는 OpenAI Embedding 클라이언트를 캐시에서 반환한다.

    Args:
        model: Embedding 모델 이름
        dimensions: 고정할 Vector 차원. None이면 모델 기본 차원 사용

    Returns:
        embed_documents를 제공하는 클라이언트
    """
    key = (model, dimensions)
    if key not in _clients:
        from openai import OpenAI

        sdk_client = OpenAI(max_retries=0, timeout=_DEFAULT_TIMEOUT_SECONDS)
        _clients[key] = _RetryingEmbeddingClient(
            model,
            lambda texts: _create_openai_embedding_call(
                sdk_client,
                texts,
                model=model,
                dimensions=dimensions,
            ),
        )
    return _clients[key]


def embed_texts(
    texts: list[str], *, model: str, dimensions: int | None = None
) -> list[list[float]]:
    """문자열 목록을 지정 모델·차원의 Embedding Vector 목록으로 변환한다."""
    if not texts:
        return []
    return get_embedding_client(model, dimensions=dimensions).embed_documents(texts)
