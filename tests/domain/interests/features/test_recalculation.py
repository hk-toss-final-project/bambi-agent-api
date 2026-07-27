"""INT-011 관심사 프로필 재계산 흐름을 검증한다."""

import asyncio
from collections.abc import Mapping, Sequence

import pytest

from domain.interests.api import ActiveWikiRequiredError, int_011
from shared.wiki_models import InterestCandidate


class _FakeRepository:
    """결정적인 Wiki 노드와 저장 호출 기록을 제공하는 저장소 대역."""

    def __init__(
        self,
        *,
        wiki_version_id: object,
        node_count: int = 1,
        signals: Sequence[Mapping[str, object]] = (),
    ) -> None:
        """활성 Wiki Version 존재 여부와 노드 수·행동 신호를 구성한다."""
        self._wiki_version_id = wiki_version_id
        self._node_count = node_count
        self._signals = list(signals)
        self.saved_candidates: Sequence[InterestCandidate] | None = None

    async def load_recent_feedback_signals(
        self, user_id: str
    ) -> Sequence[Mapping[str, object]]:
        """구성된 행동 신호를 반환한다."""
        return self._signals

    async def load_interest_documents(self, user_id: str) -> Mapping[str, object]:
        """활성 Wiki Build와 Entity·Concept 노드를 반환한다."""
        return {
            "wiki_version_id": self._wiki_version_id,
            "documents": [
                {
                    "document_id": f"document-{index}",
                    "document_kind": "entity",
                    "document_key": f"node-{index}",
                    "title": f"LangGraph Agent {index}",
                    "domain": "technology",
                    "source_metadata": {"aliases": []},
                    "degree": float(self._node_count - index),
                    "source_count": 1,
                    "source_types": ["web_clipping"],
                    "last_activity_at": "2026-07-20T00:00:00+00:00",
                }
                for index in range(self._node_count)
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


def test_int_011_extracts_scores_and_saves_new_profile() -> None:
    """Wiki 노드에서 후보를 추출해 점수를 계산하고 저장하는지 검증한다."""
    repository = _FakeRepository(wiki_version_id="wiki-version-1")

    payload = asyncio.run(int_011(repository, "user-1", limit=5))

    assert payload["wiki_version_id"] == "wiki-version-1"
    assert repository.saved_candidates is not None
    topics = {candidate.topic for candidate in repository.saved_candidates}
    assert "LangGraph Agent 0" in topics
    evidence = repository.saved_candidates[0].evidence
    assert "behavior_intensity" in evidence
    assert "recency_factor" in evidence


def test_int_011_saves_at_most_the_requested_limit() -> None:
    """후보를 넓게 추출하더라도 저장은 limit 개수를 넘지 않는지 검증한다."""
    repository = _FakeRepository(wiki_version_id="wiki-version-1", node_count=12)

    asyncio.run(int_011(repository, "user-1", limit=3))

    assert repository.saved_candidates is not None
    assert len(repository.saved_candidates) == 3


def test_int_011_requires_active_wiki() -> None:
    """활성 Wiki Build가 없으면 도메인 오류를 발생시키는지 검증한다."""
    repository = _FakeRepository(wiki_version_id=None)

    with pytest.raises(ActiveWikiRequiredError):
        asyncio.run(int_011(repository, "user-1", limit=5))
    assert repository.saved_candidates is None


def test_int_011_applies_feedback_signals_to_scores() -> None:
    """재계산이 행동 신호(INT-005)를 반영해 점수를 보정하는지 검증한다."""
    from datetime import UTC, datetime

    repository = _FakeRepository(
        wiki_version_id="wiki-version-1",
        signals=[
            {
                "topic": "Python",
                "signal_type": "like",
                "occurred_at": datetime(2026, 7, 27, tzinfo=UTC),
            }
        ],
    )

    asyncio.run(int_011(repository, "user-1", limit=5))

    assert repository.saved_candidates is not None
    python = next(
        candidate
        for candidate in repository.saved_candidates
        if candidate.topic.casefold() == "python"
    )
    assert "behavior:like" in python.evidence["reasons"]
    assert float(python.evidence["behavior_boost"]) > 0
