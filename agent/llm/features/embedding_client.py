"""공유 Embedding 호출 경계.

OpenAI Embedding 클라이언트 생성·캐시를 한 곳에 모아, 도메인별로 설정
(dimensions)이 어긋난 클라이언트가 중복 생성되지 않게 한다.
"""

from __future__ import annotations

from typing import Protocol


class EmbeddingClient(Protocol):
    """문자열 목록을 Vector 목록으로 변환하는 Client 계약."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """입력 문자열과 같은 순서의 Embedding Vector를 반환한다."""
        ...


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
        from langchain_openai import OpenAIEmbeddings

        if dimensions is None:
            _clients[key] = OpenAIEmbeddings(model=model)
        else:
            _clients[key] = OpenAIEmbeddings(model=model, dimensions=dimensions)
    return _clients[key]


def embed_texts(
    texts: list[str], *, model: str, dimensions: int | None = None
) -> list[list[float]]:
    """문자열 목록을 지정 모델·차원의 Embedding Vector 목록으로 변환한다."""
    if not texts:
        return []
    return get_embedding_client(model, dimensions=dimensions).embed_documents(texts)
