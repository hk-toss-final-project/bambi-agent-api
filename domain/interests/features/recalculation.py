"""관심사 프로필 재계산 기능 구현.

INT-011의 실제 구현 위치다. 활성 Wiki Build의 문서를 읽어 INT-001로
관심 후보를 추출하고, 주입된 저장소 경계에 새 관심 Profile Version으로
저장한다.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol

from domain.interests.features.extraction import int_001
from domain.interests.features.scoring import int_005
from shared.wiki_models import InterestCandidate


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

    활성 Wiki 문서에서 관심 후보를 다시 추출해 새 Profile로 저장한다.

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
    candidates = await int_001(document_rows, limit=limit)
    signals = await repository.load_recent_feedback_signals(user_id)
    if signals:
        candidates = (await int_005(candidates, signals=signals))[:limit]
    return await repository.save_interest_profile(
        user_id, wiki_version_id=wiki_version_id, candidates=candidates
    )
