"""INT-011 관심사 프로필 재계산 흐름을 검증한다."""

import asyncio
from collections.abc import Mapping, Sequence

import pytest

from domain.interests.api import ActiveWikiRequiredError, int_011
from shared.wiki_models import InterestCandidate


class _FakeRepository:
    """결정적인 Wiki 문서와 저장 호출 기록을 제공하는 저장소 대역."""

    def __init__(self, *, wiki_version_id: object) -> None:
        """활성 Wiki Version 존재 여부를 구성한다."""
        self._wiki_version_id = wiki_version_id
        self.saved_candidates: Sequence[InterestCandidate] | None = None

    async def load_interest_documents(self, user_id: str) -> Mapping[str, object]:
        """활성 Wiki Build와 문서 한 건을 반환한다."""
        return {
            "wiki_version_id": self._wiki_version_id,
            "documents": [
                {
                    "document_id": "document-1",
                    "title": "LangGraph Agent",
                    "summary": "LangGraph 기반 에이전트 오케스트레이션",
                    "domain": "technology",
                    "source_metadata": {"tags": ["Python"]},
                }
            ],
        }

    async def save_interest_profile(
        self,
        user_id: str,
        *,
        wiki_version_id: str,
        candidates: Sequence[InterestCandidate],
    ) -> Mapping[str, object]:
        """전달된 후보를 기록하고 저장 결과 Payload를 반환한다."""
        self.saved_candidates = candidates
        return {
            "profile_id": "profile-1",
            "user_id": user_id,
            "wiki_version_id": wiki_version_id,
            "candidate_count": len(candidates),
        }


def test_int_011_extracts_and_saves_new_profile() -> None:
    """활성 Wiki 문서에서 후보를 추출해 저장하고 Payload를 반환하는지 검증한다."""
    repository = _FakeRepository(wiki_version_id="wiki-version-1")

    payload = asyncio.run(int_011(repository, "user-1", limit=5))

    assert payload["wiki_version_id"] == "wiki-version-1"
    assert repository.saved_candidates is not None
    topics = {candidate.topic for candidate in repository.saved_candidates}
    assert "LangGraph Agent" in topics


def test_int_011_requires_active_wiki() -> None:
    """활성 Wiki Build가 없으면 도메인 오류를 발생시키는지 검증한다."""
    repository = _FakeRepository(wiki_version_id=None)

    with pytest.raises(ActiveWikiRequiredError):
        asyncio.run(int_011(repository, "user-1", limit=5))
    assert repository.saved_candidates is None
