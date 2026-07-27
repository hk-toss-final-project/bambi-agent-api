"""임베딩 호출 경계와 코사인 유사도.

토픽·문서 텍스트를 벡터화한다. 실제 호출은 공유 Embedding 클라이언트
(agent/llm — 클라이언트 캐시 일원화)에 위임하고, 이 모듈은 비서 기능이
대체하기 쉬운 경계(embed_texts 심볼)와 비서 고유의 입력 다듬기만 유지한다.
코사인 유사도는 외부 의존성 없이 순수 파이썬으로 계산한다
(하루 수집 문서 수십 건 규모라 numpy가 필요 없다).
"""

from __future__ import annotations

import math

from agent.selection.features import config
from agent.llm.api import embed_texts as _shared_embed_texts

# 임베딩 입력이 지나치게 길면 비용이 커지므로 상한 문자수로 자른다.
_MAX_INPUT_CHARS = 2000


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
    trimmed = [(text.strip()[:_MAX_INPUT_CHARS] or " ") for text in texts]
    return _shared_embed_texts(trimmed, model=model or config.EMBEDDING_MODEL)


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
