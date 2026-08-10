"""Report Builder 개인 Wiki 검색 Query Embedding 경계.

외부 Embedding 호출을 DB Transaction 밖에서 수행하고, Provider 장애나 차원 불일치를
Keyword 검색 폴백으로 격리한다.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence

from agent.llm.api import embed_texts
from domain.personal_wiki.retrieval.api import (
    DEFAULT_WIKI_EMBEDDING_MODEL,
    WIKI_EMBEDDING_DIMENSIONS,
)

logger = logging.getLogger("agent.report_builder.wiki_retrieval")


def embed_wiki_queries(
    queries: Sequence[str],
    *,
    model: str = DEFAULT_WIKI_EMBEDDING_MODEL,
) -> dict[str, tuple[float, ...]]:
    """개인 Wiki 검색어를 한 번에 Embedding하고 실패 Query는 제외한다.

    Args:
        queries: 의미 검색에 사용할 검색어 목록
        model: Wiki Chunk 저장 시 사용한 Embedding 모델 이름

    Returns:
        원본 정규화 검색어별 1536차원 Vector. Provider 실패 시 빈 사전
    """
    normalized = list(
        dict.fromkeys(query.strip() for query in queries if query.strip())
    )
    if not normalized:
        return {}
    try:
        vectors = embed_texts(
            normalized,
            model=model,
            dimensions=WIKI_EMBEDDING_DIMENSIONS,
        )
    except Exception as error:  # noqa: BLE001 - Keyword 폴백을 위한 장애 격리
        logger.warning("Wiki Query Embedding 실패, Keyword 검색으로 폴백합니다: %s", error)
        return {}
    if len(vectors) != len(normalized):
        logger.warning(
            "Wiki Query Embedding 응답 개수 불일치, Keyword 검색으로 폴백합니다."
        )
        return {}
    result: dict[str, tuple[float, ...]] = {}
    for query, raw_vector in zip(normalized, vectors, strict=True):
        try:
            vector = tuple(float(value) for value in raw_vector)
        except (TypeError, ValueError):
            logger.warning(
                "Wiki Query Embedding 숫자 검증 실패(query=%s), 해당 Query는 "
                "Keyword 검색으로 폴백합니다.",
                query,
            )
            continue
        if len(vector) != WIKI_EMBEDDING_DIMENSIONS or not all(
            math.isfinite(value) for value in vector
        ):
            logger.warning(
                "Wiki Query Embedding 차원·값 검증 실패(query=%s), 해당 Query는 "
                "Keyword 검색으로 폴백합니다.",
                query,
            )
            continue
        result[query] = vector
    return result
