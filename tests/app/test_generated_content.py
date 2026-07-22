"""저장된 Report Builder 콘텐츠 목록·상세 조회 서비스를 검증한다."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.exceptions import AgentApiError
from app.services.generated_content import GeneratedContentService


class _FakeGeneratedContentRepository:
    """목록·상세 조회용 생성 콘텐츠 Payload를 제공한다."""

    async def list_generated_contents(
        self, user_id: str, *, limit: int, offset: int
    ) -> dict[str, object]:
        """고정 생성 콘텐츠 목록을 반환한다."""
        assert (user_id, limit, offset) == ("user-1", 20, 0)
        return {
            "user_id": user_id,
            "total": 1,
            "items": [
                {
                    "candidate_id": "candidate-1",
                    "content_id": "content-1",
                    "version": 1,
                    "content_type": "interest_news_card",
                    "status": "ready",
                    "title": "제목",
                    "summary": "요약",
                    "created_at": datetime.now(UTC),
                }
            ],
        }

    async def get_generated_content(
        self, user_id: str, candidate_id: str
    ) -> dict[str, object] | None:
        """소유한 후보만 상세 Payload로 반환한다."""
        if (user_id, candidate_id) != ("user-1", "candidate-1"):
            return None
        return {
            "candidate_id": candidate_id,
            "content_id": "content-1",
            "version": 1,
            "content_type": "interest_news_card",
            "status": "ready",
            "title": "제목",
            "summary": "요약",
            "created_at": datetime.now(UTC),
            "feature_id": "REPORT-018",
            "user_id": user_id,
            "body": "본문 [P1]",
            "structured_body": {"format": "markdown"},
            "snapshot_hash": "a" * 64,
            "generation_request_id": "request-1",
            "generation_run_id": "run-1",
            "latency_ms": 10,
            "citations": [
                {
                    "citation_id": "citation-1",
                    "ordinal": 0,
                    "reference": "P1",
                    "document_version_id": "version-1",
                    "chunk_id": "chunk-1",
                    "title": "개인 Wiki",
                }
            ],
        }


def test_generated_content_service_validates_list_and_detail() -> None:
    """Repository Payload가 목록·본문·Citation 응답 모델로 검증되는지 확인한다."""
    service = GeneratedContentService(_FakeGeneratedContentRepository())

    listed = asyncio.run(service.list_contents("user-1", limit=20, offset=0))
    detail = asyncio.run(service.get_content("user-1", "candidate-1"))

    assert listed.total == 1
    assert detail.body == "본문 [P1]"
    assert detail.citations[0].reference == "P1"


def test_generated_content_service_hides_unknown_or_foreign_candidate() -> None:
    """존재하지 않거나 다른 사용자 후보를 같은 404 오류로 숨긴다."""
    service = GeneratedContentService(_FakeGeneratedContentRepository())

    with pytest.raises(AgentApiError) as raised:
        asyncio.run(service.get_content("user-2", "candidate-1"))

    assert raised.value.status_code == 404
    assert raised.value.detail.code == "GENERATED_CONTENT_NOT_FOUND"
