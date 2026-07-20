"""개인 Wiki Chunk Embedding 생성 경계.

OpenAI Embedding Provider 호출을 한 모듈에 격리해 Worker 테스트에서
결정적인 가짜 Client로 대체할 수 있게 한다.
"""

from collections.abc import Callable, Sequence
from typing import Protocol

from infrastructure.persistence.api import WikiChunkForEmbedding, WikiEmbeddingValue

from shared.contracts import FeatureRequest, FeatureResult


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


async def wba_011(request: FeatureRequest) -> FeatureResult:
    """[WBA-011] Wiki 재임베딩.

    변경된 문서와 구조의 Embedding을 갱신한다.
    """
    raise NotImplementedError("[WBA-011] 기능 구현이 필요합니다.")
