"""임베딩 클러스터링(clustering)과 코사인 유사도(embeddings) 검증."""

import pytest

from agent.assistant.features import clustering
from agent.assistant.features.embeddings import cosine_similarity


def test_cosine_similarity_basic() -> None:
    """코사인 유사도의 기본 성질: 같은 방향 1, 직교 0."""
    assert cosine_similarity([1.0, 0.0], [2.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_zero_or_mismatched_vectors() -> None:
    """영벡터·길이 불일치·빈 벡터는 0.0을 반환한다."""
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert cosine_similarity([1.0], [1.0, 0.0]) == 0.0
    assert cosine_similarity([], []) == 0.0


def test_greedy_clusters_groups_similar_documents() -> None:
    """유사한 문서는 같은 클러스터로, 다른 주제는 별도 클러스터로 묶는다."""
    embeddings = [
        [1.0, 0.0],   # A
        [0.99, 0.05], # A와 유사
        [0.0, 1.0],   # 전혀 다른 주제
    ]
    clusters = clustering.greedy_clusters(embeddings, threshold=0.8)

    assert clusters == [[0, 1], [2]]


def test_greedy_clusters_respects_threshold() -> None:
    """threshold를 높이면 애매한 문서가 별도 클러스터로 분리된다."""
    embeddings = [
        [1.0, 0.0],
        [0.8, 0.6],  # cos = 0.8
    ]
    assert clustering.greedy_clusters(embeddings, threshold=0.79) == [[0, 1]]
    assert clustering.greedy_clusters(embeddings, threshold=0.9) == [[0], [1]]


def test_greedy_clusters_links_through_any_member() -> None:
    """시드와는 멀어도 다른 멤버와 가까우면 같은 클러스터에 편입한다.

    같은 사건 기사는 A-B, B-C는 가깝지만 A-C는 먼 경우가 흔하다. 시드(A)와만
    비교하면 C가 떨어져 나가 같은 사건이 여러 클러스터로 쪼개진다.
    """
    embeddings = [
        [1.0, 0.0],    # A (시드)
        [0.8, 0.6],    # B: A와 cos 0.80
        [0.6, 0.8],    # C: A와 cos 0.60, B와 cos 0.96
    ]
    # 컷 0.7 → C는 시드 A(0.60)와는 미달이지만 멤버 B(0.96)와 맞아 편입된다.
    assert clustering.greedy_clusters(embeddings, threshold=0.7) == [[0, 1, 2]]


def test_greedy_clusters_keeps_unrelated_documents_apart() -> None:
    """어느 멤버와도 기준에 못 미치면 별도 클러스터로 남는다 (과병합 방지)."""
    embeddings = [
        [1.0, 0.0],
        [0.95, 0.31],  # 첫 문서와 cos ≈ 0.95
        [0.0, 1.0],    # 두 문서 모두와 먼 문서
    ]
    assert clustering.greedy_clusters(embeddings, threshold=0.7) == [[0, 1], [2]]


def test_greedy_clusters_empty_input() -> None:
    """빈 입력은 빈 클러스터 목록을 반환한다."""
    assert clustering.greedy_clusters([]) == []
