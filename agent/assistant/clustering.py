"""임베딩 유사도 기반 주제 클러스터링.

당일 수집 문서들을 코사인 유사도 그리디 방식으로 주제별로 묶는다. 문서 수가
하루 수십 건 규모라 HDBSCAN 같은 라이브러리 없이 O(n²) 순수 파이썬으로 충분하다.

같은 클러스터의 문서들은 개별 요약하지 않고 하나의 아티클로 통합 요약되며
(pipeline 담당), 클러스터 대표 점수는 클러스터 내 최고 final_score를 쓴다.
"""

from __future__ import annotations

from agent.assistant import config
from agent.assistant.embeddings import cosine_similarity


def greedy_clusters(
    embeddings: list[list[float]],
    threshold: float | None = None,
) -> list[list[int]]:
    """임베딩 목록을 그리디 방식으로 클러스터링해 인덱스 그룹을 반환한다.

    각 문서를 순서대로 보며, 기존 클러스터의 시드(첫 문서)와의 코사인 유사도가
    threshold 이상이면 그 클러스터에 편입하고, 아니면 새 클러스터를 만든다.
    시드 비교 방식이라 결과가 입력 순서에 대해 결정적이다.

    Args:
        embeddings: 문서 임베딩 목록
        threshold: 같은 클러스터로 묶는 유사도 기준. 생략 시 config 값.

    Returns:
        클러스터별 문서 인덱스 리스트 (입력 순서 유지)
    """
    cutoff = config.CLUSTER_SIM_THRESHOLD if threshold is None else threshold
    clusters: list[list[int]] = []
    for index, embedding in enumerate(embeddings):
        placed = False
        for cluster in clusters:
            seed = embeddings[cluster[0]]
            if cosine_similarity(seed, embedding) >= cutoff:
                cluster.append(index)
                placed = True
                break
        if not placed:
            clusters.append([index])
    return clusters
