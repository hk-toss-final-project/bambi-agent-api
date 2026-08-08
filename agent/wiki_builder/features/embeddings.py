"""개인 Wiki Chunk Embedding 생성 경계.

OpenAI Embedding Provider 호출을 한 모듈에 격리해 Worker 테스트에서
결정적인 가짜 Client로 대체할 수 있게 한다.
"""

from asyncio import to_thread
from collections.abc import Callable, Sequence
from functools import partial
from typing import Any, Protocol

from psycopg import AsyncConnection

from infrastructure.persistence.api import (
    WikiChunkForEmbedding,
    WikiEmbeddingValue,
    get_wiki_chunks_for_embedding,
    persist_wiki_embeddings,
    set_personal_wiki_scope,
)

type DictRow = dict[str, Any]


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


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wba_011(
    connection: AsyncConnection[DictRow],
    *,
    namespace_key: str,
    document_version_ids: Sequence[str],
    model: str = "text-embedding-3-small",
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
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        chunks = await get_wiki_chunks_for_embedding(
            connection,
            namespace_key=namespace_key,
            document_version_ids=document_version_ids,
        )
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
