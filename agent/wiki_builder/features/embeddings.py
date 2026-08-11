"""개인 Wiki Chunk Embedding 생성 경계.

OpenAI Embedding Provider 호출을 한 모듈에 격리해 Worker 테스트에서
결정적인 가짜 Client로 대체할 수 있게 한다.
"""

from asyncio import to_thread
from collections.abc import Callable, Sequence
from functools import partial
from hashlib import sha256
from typing import Any, Protocol

from psycopg import AsyncConnection

from infrastructure.persistence.api import (
    ClaimedBatchResultItem,
    EnqueueLlmBatchItemCommand,
    WikiChunkForEmbedding,
    WikiEmbeddingValue,
    get_wiki_chunks_for_embedding,
    enqueue_llm_batch_item,
    persist_wiki_embeddings,
    set_personal_wiki_scope,
)

type DictRow = dict[str, Any]

_BATCH_INPUTS_PER_ITEM = 128
_EMBEDDING_DIMENSIONS = 1536


class EmbeddingClient(Protocol):
    """Wiki Chunk 목록을 Vector 목록으로 변환하는 Client 계약."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """입력 문자열과 같은 순서의 Embedding Vector를 반환한다."""
        ...


def _default_client(model: str) -> EmbeddingClient:
    """공유 캐시에서 1536차원 OpenAI Embedding Client를 가져온다."""
    from agent.llm.api import get_embedding_client

    return get_embedding_client(model, dimensions=1536)


def generate_wiki_embeddings(
    chunks: Sequence[WikiChunkForEmbedding],
    *,
    model: str = "text-embedding-3-small",
    client_factory: Callable[[str], EmbeddingClient] = _default_client,
) -> list[WikiEmbeddingValue]:
    """Wiki Chunk를 1536차원 Vector로 변환하고 Chunk ID와 다시 결합한다."""
    if not chunks:
        return []
    client = client_factory(model)
    vectors = client.embed_documents([chunk.content for chunk in chunks])
    if len(vectors) != len(chunks):
        raise RuntimeError(
            "Embedding Provider의 Vector 개수가 Wiki Chunk 개수와 다릅니다."
        )
    return [
        WikiEmbeddingValue(
            chunk_id=chunk.chunk_id,
            content=chunk.content,
            embedding=list(vector),
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]


def generate_relation_query_embeddings(
    texts: Sequence[str],
    *,
    model: str = "text-embedding-3-small",
    client_factory: Callable[[str], EmbeddingClient] = _default_client,
) -> list[tuple[float, ...]]:
    """Relation Linker 후보 recall용 문장을 같은 모델 Vector로 변환한다."""
    if not texts:
        return []
    vectors = client_factory(model).embed_documents(list(texts))
    if len(vectors) != len(texts):
        raise RuntimeError(
            "Embedding Provider의 Vector 개수가 관계 Query 개수와 다릅니다."
        )
    return [tuple(vector) for vector in vectors]


def _embedding_batch_custom_id(
    namespace_key: str,
    model: str,
    chunks: Sequence[WikiChunkForEmbedding],
) -> str:
    """사용자 원문을 노출하지 않는 결정적 Wiki Embedding custom_id를 만든다."""
    signature = "\n".join(
        [namespace_key, model, *(f"{chunk.chunk_id}:{chunk.content}" for chunk in chunks)]
    )
    return f"wiki-embedding:{sha256(signature.encode('utf-8')).hexdigest()}"


async def enqueue_wiki_embedding_batches(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    namespace_key: str,
    chunks: Sequence[WikiChunkForEmbedding],
    model: str,
    job_id: str | None,
) -> int:
    """Wiki Chunk를 고정 크기로 나눠 멱등 OpenAI Embedding Batch Item으로 등록한다."""
    enqueued = 0
    for offset in range(0, len(chunks), _BATCH_INPUTS_PER_ITEM):
        shard = list(chunks[offset : offset + _BATCH_INPUTS_PER_ITEM])
        await enqueue_llm_batch_item(
            connection,
            EnqueueLlmBatchItemCommand(
                user_id=user_id,
                job_id=job_id,
                custom_id=_embedding_batch_custom_id(namespace_key, model, shard),
                endpoint="/v1/embeddings",
                model_name=model,
                workload="wiki_embedding",
                resource_type="wiki_chunk_set",
                resource_id=shard[0].chunk_id,
                request_body={
                    "model": model,
                    "input": [chunk.content for chunk in shard],
                    "dimensions": _EMBEDDING_DIMENSIONS,
                    "encoding_format": "float",
                },
                context={
                    "namespace_key": namespace_key,
                    "chunks": [
                        {"chunk_id": chunk.chunk_id, "content": chunk.content}
                        for chunk in shard
                    ],
                },
            ),
        )
        enqueued += 1
    return enqueued


def _wiki_embedding_values_from_batch(
    item: ClaimedBatchResultItem,
) -> tuple[str, list[WikiEmbeddingValue]]:
    """Batch 응답 Vector를 Context의 Chunk ID·본문과 검증해 다시 결합한다."""
    namespace_key = str(item.context.get("namespace_key") or "")
    raw_chunks = item.context.get("chunks")
    raw_data = item.result_body.get("data")
    if not namespace_key.startswith("user/"):
        raise ValueError("Wiki Embedding Batch Context의 Namespace가 잘못됐습니다.")
    if not isinstance(raw_chunks, list) or not isinstance(raw_data, list):
        raise ValueError("Wiki Embedding Batch 결과에 Chunk 또는 Vector가 없습니다.")
    if len(raw_chunks) != len(raw_data):
        raise ValueError("Wiki Embedding Batch의 Chunk와 Vector 개수가 다릅니다.")
    ordered = sorted(
        raw_data,
        key=lambda value: int(value.get("index", -1))
        if isinstance(value, dict)
        else -1,
    )
    values: list[WikiEmbeddingValue] = []
    for expected_index, (chunk, result) in enumerate(
        zip(raw_chunks, ordered, strict=True)
    ):
        if not isinstance(chunk, dict) or not isinstance(result, dict):
            raise ValueError("Wiki Embedding Batch Item 형식이 잘못됐습니다.")
        if int(result.get("index", -1)) != expected_index:
            raise ValueError("Wiki Embedding Batch Vector Index가 연속적이지 않습니다.")
        vector = result.get("embedding")
        if not isinstance(vector, list) or len(vector) != _EMBEDDING_DIMENSIONS:
            raise ValueError("Wiki Embedding Batch Vector 차원이 1536이 아닙니다.")
        values.append(
            WikiEmbeddingValue(
                chunk_id=str(chunk.get("chunk_id") or ""),
                content=str(chunk.get("content") or ""),
                embedding=[float(value) for value in vector],
            )
        )
    if any(not value.chunk_id for value in values):
        raise ValueError("Wiki Embedding Batch Context에 Chunk ID가 없습니다.")
    return namespace_key, values


async def apply_wiki_embedding_batch_result(
    connection: AsyncConnection[DictRow],
    item: ClaimedBatchResultItem,
) -> int:
    """완료된 Embedding Batch 결과를 기존 Wiki Vector Upsert 경계로 반영한다."""
    if item.workload != "wiki_embedding":
        raise ValueError("Wiki Embedding Handler가 다른 workload를 받았습니다.")
    namespace_key, values = _wiki_embedding_values_from_batch(item)
    user_id = namespace_key.removeprefix("user/")
    if user_id != item.user_id:
        raise ValueError("Wiki Embedding Batch Item의 사용자 Scope가 일치하지 않습니다.")
    await set_personal_wiki_scope(connection, user_id=user_id)
    return await persist_wiki_embeddings(
        connection,
        namespace_key=namespace_key,
        model_name=item.model_name,
        values=values,
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wba_011(
    connection: AsyncConnection[DictRow],
    *,
    namespace_key: str,
    document_version_ids: Sequence[str],
    model: str = "text-embedding-3-small",
    job_id: str | None = None,
    batch_threshold: int = 0,
    client_factory: Callable[[str], EmbeddingClient] = _default_client,
) -> int:
    """[WBA-011] Wiki 재임베딩.

    변경된 문서와 구조의 Embedding을 갱신한다.
    """
    if not namespace_key.startswith("user/"):
        raise ValueError("WBA-011은 user/{user_id} Namespace만 재임베딩합니다.")
    user_id = namespace_key.removeprefix("user/")
    if not user_id:
        raise ValueError("WBA-011 Namespace에 user_id가 없습니다.")
    if batch_threshold < 0:
        raise ValueError("WBA-011 batch_threshold는 0 이상이어야 합니다.")
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        chunks = await get_wiki_chunks_for_embedding(
            connection,
            namespace_key=namespace_key,
            document_version_ids=document_version_ids,
        )
    if batch_threshold > 0 and len(chunks) >= batch_threshold:
        async with connection.transaction():
            await set_personal_wiki_scope(connection, user_id=user_id)
            await enqueue_wiki_embedding_batches(
                connection,
                user_id=user_id,
                namespace_key=namespace_key,
                chunks=chunks,
                model=model,
                job_id=job_id,
            )
        return 0
    values = await to_thread(
        partial(
            generate_wiki_embeddings,
            chunks,
            model=model,
            client_factory=client_factory,
        )
    )
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        return await persist_wiki_embeddings(
            connection,
            namespace_key=namespace_key,
            model_name=model,
            values=values,
        )
