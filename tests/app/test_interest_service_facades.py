"""관심사 애플리케이션 서비스와 INT facade의 연동을 검증한다."""

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import pytest

from app.exceptions import AgentApiError
from app.services.interests import InterestService
from shared.wiki_models import InterestCandidate


class _FakeInterestRepository:
    """결정적인 Wiki 문서와 저장 결과를 반환하는 관심사 저장소 대역."""

    def __init__(self, *, wiki_version_id: object = "wiki-version-1") -> None:
        """활성 Wiki Version 존재 여부를 구성한다."""
        self._wiki_version_id = wiki_version_id

    async def load_interest_documents(self, user_id: str) -> Mapping[str, object]:
        """관심사 추출에 사용할 활성 Wiki 문서 한 건을 반환한다."""
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
        """계산된 첫 후보를 활성 관심사 Profile 응답으로 변환한다."""
        candidate = candidates[0]
        return {
            "profile_id": "profile-1",
            "user_id": user_id,
            "wiki_version_id": wiki_version_id,
            "version": 1,
            "status": "active",
            "calculated_at": datetime.now(UTC),
            "interests": [
                {
                    "interest_id": "interest-1",
                    "topic": candidate.topic,
                    "category": candidate.category,
                    "score": candidate.score,
                    "confidence": candidate.confidence,
                    "document_ids": list(candidate.document_ids),
                    "evidence": dict(candidate.evidence),
                }
            ],
        }

    async def list_interests(self, user_id: str) -> Mapping[str, object] | None:
        """이 테스트에서 사용하지 않는 활성 Profile 조회 결과를 반환한다."""
        return None


def test_rebuild_runs_int_011_and_validates_response() -> None:
    """관심사 재계산이 INT-011 facade를 거쳐 검증된 응답을 만드는지 검증한다."""
    service = InterestService(_FakeInterestRepository())

    result = asyncio.run(service.rebuild("user-1", limit=5))

    assert result.feature_id == "INT-001"
    assert result.user_id == "user-1"
    assert result.wiki_version_id == "wiki-version-1"
    assert result.interests[0].topic == "LangGraph Agent"


def test_rebuild_maps_missing_active_wiki_to_conflict() -> None:
    """활성 Wiki가 없으면 도메인 오류를 409 API 오류로 변환하는지 검증한다."""
    service = InterestService(_FakeInterestRepository(wiki_version_id=None))

    with pytest.raises(AgentApiError) as raised:
        asyncio.run(service.rebuild("user-1", limit=5))
    assert raised.value.status_code == 409
    assert raised.value.detail.code == "ACTIVE_WIKI_REQUIRED"
