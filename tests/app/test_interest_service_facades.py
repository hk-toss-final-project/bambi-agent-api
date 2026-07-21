"""관심사 애플리케이션 서비스의 facade 실행 경계를 검증한다."""

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from agent.wiki_builder.api import InterestCandidate
from app.services.interests import InterestService


class _FakeInterestRepository:
    """결정적인 Wiki 문서와 저장 결과를 반환하는 관심사 저장소 대역."""

    async def load_interest_documents(self, user_id: str) -> Mapping[str, object]:
        """관심사 추출에 사용할 활성 Wiki 문서 한 건을 반환한다."""
        return {
            "wiki_version_id": "wiki-version-1",
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


def test_rebuild_runs_interest_feature_facades() -> None:
    """관심사 재계산 결과가 추출·분류·점수 facade를 거쳐 저장된다."""
    service = InterestService(_FakeInterestRepository())

    result = asyncio.run(service.rebuild("user-1", limit=5))

    assert result.feature_id == "INT-001"
    assert result.user_id == "user-1"
    assert result.wiki_version_id == "wiki-version-1"
    assert result.interests[0].topic == "LangGraph Agent"
