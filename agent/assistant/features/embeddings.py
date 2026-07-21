"""임베딩 호출 경계와 코사인 유사도.

토픽·문서 텍스트를 OpenAI 임베딩(langchain-openai)으로 벡터화한다. 실제 API를
호출하는 경계를 이 모듈로 모아 테스트에서 embed_texts만 대체하면 네트워크 호출을
막을 수 있다. 코사인 유사도는 외부 의존성 없이 순수 파이썬으로 계산한다
(하루 수집 문서 수십 건 규모라 numpy가 필요 없다).
"""

from __future__ import annotations

import math

from agent.assistant.features import config

# OpenAIEmbeddings 클라이언트를 모델별로 한 번만 생성해 재사용한다.
_clients: dict[str, object] = {}

# 임베딩 입력이 지나치게 길면 비용이 커지므로 상한 문자수로 자른다.
_MAX_INPUT_CHARS = 2000


def _get_client(model: str) -> object:
    """모델 이름에 해당하는 OpenAIEmbeddings 클라이언트를 반환한다."""
    if model not in _clients:
        from langchain_openai import OpenAIEmbeddings

        _clients[model] = OpenAIEmbeddings(model=model)
    return _clients[model]


def embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    """텍스트 목록을 임베딩 벡터 목록으로 변환한다 (네트워크 경계).

    Args:
        texts: 임베딩할 텍스트 목록 (빈 문자열은 공백 하나로 대체해 호출한다)
        model: 임베딩 모델 이름. 생략하면 config.EMBEDDING_MODEL.

    Returns:
        입력과 같은 순서의 임베딩 벡터 리스트
    """
    if not texts:
        return []
    client = _get_client(model or config.EMBEDDING_MODEL)
    trimmed = [(text.strip()[:_MAX_INPUT_CHARS] or " ") for text in texts]
    return client.embed_documents(trimmed)


def embed_text(text: str, model: str | None = None) -> list[float]:
    """텍스트 하나를 임베딩 벡터로 변환한다."""
    return embed_texts([text], model=model)[0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """두 벡터의 코사인 유사도를 계산한다. 영벡터가 있으면 0.0을 반환한다."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
