"""관심사 프로필 재계산 기능 구현.

INT-011의 실제 구현 위치다. 활성 Wiki Build의 Entity·Concept 노드를 읽어
INT-001로 관심 후보를 추출하고, INT-005로 최신성·행동 강도 점수를 계산한 뒤,
주입된 저장소 경계에 새 관심 Profile Version으로 저장한다.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol

from domain.interests.features.extraction import int_001
from domain.interests.features.scoring import int_005
from shared.wiki_models import InterestCandidate

# 점수 계산 전에 후보를 성급히 잘라내지 않도록 저장 한도보다 넓게 추출한다.
_CANDIDATE_POOL_MULTIPLIER = 3
_MAX_CANDIDATE_POOL = 100


class ActiveWikiRequiredError(Exception):
    """관심사를 계산할 활성 개인 Wiki가 없을 때 발생하는 도메인 오류."""


class InterestProfileRepository(Protocol):
    """관심사 재계산이 사용하는 영속 저장소 경계."""

    async def load_interest_documents(self, user_id: str) -> Mapping[str, object]:
        """활성 Wiki Build와 현재 Wiki 문서를 반환한다."""
        ...

    async def save_interest_profile(
        self,
        user_id: str,
        *,
        wiki_version_id: str,
        candidates: Sequence[InterestCandidate],
    ) -> Mapping[str, object]:
        """새 관심 Profile Version과 근거를 저장한다."""
        ...

    async def load_recent_feedback_signals(
        self, user_id: str
    ) -> Sequence[Mapping[str, object]]:
        """최근 사용자 행동 신호를 Topic 단위로 반환한다."""
        ...


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def int_011(
    repository: InterestProfileRepository, user_id: str, *, limit: int = 20
) -> Mapping[str, object]:
    """[INT-011] 관심사 프로필 재계산.

    활성 Wiki 노드에서 관심 후보를 다시 추출하고(INT-001) 최신성·행동 강도
    점수를 계산해(INT-005) 새 Profile로 저장한다.

    Args:
        repository: 관심사 문서 조회·Profile 저장 경계
        user_id: 재계산 대상 사용자 ID
        limit: 저장할 최대 관심 후보 수 (1~100)

    Returns:
        저장된 활성 관심 Profile Payload

    Raises:
        ActiveWikiRequiredError: 계산 기준이 될 활성 Wiki Build가 없는 경우
    """
    source = await repository.load_interest_documents(user_id)
    wiki_version_id = source.get("wiki_version_id")
    if not isinstance(wiki_version_id, str):
        raise ActiveWikiRequiredError(
            "관심 키워드를 계산할 활성 개인 Wiki가 필요합니다."
        )
    documents = source.get("documents")
    document_rows = documents if isinstance(documents, list) else []
    # 시드가 유일한 근거인 노드를 걸러내려면 온보딩에서 고른 라벨이 필요하다.
    seed_labels = source.get("onboarding_seed_labels")
    label_rows = seed_labels if isinstance(seed_labels, (list, tuple)) else ()
    candidate_pool = min(_MAX_CANDIDATE_POOL, limit * _CANDIDATE_POOL_MULTIPLIER)
    candidates = await int_001(
        document_rows,
        limit=max(candidate_pool, limit),
        onboarding_seed_labels=[str(label) for label in label_rows],
    )
    # 행동 신호가 없어도 Wiki 근거 기반 기본 점수는 항상 계산한다.
    signals = await repository.load_recent_feedback_signals(user_id)
    scored = await int_005(candidates, signals=signals, limit=limit)
    return await repository.save_interest_profile(
        user_id, wiki_version_id=wiki_version_id, candidates=scored
    )
