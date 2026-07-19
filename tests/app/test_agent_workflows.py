"""개발 API와 Worker가 공유하는 Agent Job 실행기를 검증한다."""

import asyncio
from datetime import UTC, datetime

from app.config import Settings
from app.services.agent_jobs import AgentJobRecord, ClaimedJobRecord
from app.services.agent_workflows import AgentWorkflowService
from infrastructure.sources.connectors.api import JinaReadResult


class _FakeAgentRepository:
    """URL·Wiki Job 실행 상태를 메모리에 기록하는 Repository Test Double."""

    def __init__(self, job_type: str = "personal_wiki_url") -> None:
        """테스트할 Job 유형과 초기 queued 상태를 준비한다."""
        now = datetime.now(UTC)
        self.record = AgentJobRecord(
            job_id="job-1",
            feature_id="SVC-003",
            job_type=job_type,
            user_id="user-1",
            idempotency_key="event-1",
            status="queued",
            progress=0,
            request_id="request-1",
            created_at=now,
            updated_at=now,
        )
        self.completed: dict[str, object] | None = None
        self.failed: str | None = None

    async def get_job(self, job_id: str) -> AgentJobRecord | None:
        """고정 Job 레코드를 반환한다."""
        return self.record if job_id == self.record.job_id else None

    async def claim_job(
        self, *, job_id: str, worker_id: str, lease_seconds: int
    ) -> ClaimedJobRecord | None:
        """고정 Job을 한 번 점유한 결과를 반환한다."""
        payload = (
            {
                "url": "https://example.com",
                "source_document_id": "source-1",
                "source_event_id": "event-1",
                "source_event_row_id": "event-row-1",
            }
            if self.record.job_type == "personal_wiki_url"
            else {"source_document_version_id": "source-version-1"}
        )
        return ClaimedJobRecord(
            job_id=job_id,
            user_id="user-1",
            feature_id=self.record.feature_id,
            job_type=self.record.job_type,
            attempt_number=1,
            max_attempts=3,
            payload=payload,
        )

    async def save_fetched_url(self, **_: object) -> dict[str, object]:
        """URL 저장 후 등록된 Wiki Job ID를 반환한다."""
        return {
            "source_document_version_id": "source-version-1",
            "wiki_build_job_id": "wiki-job-1",
            "unchanged": False,
        }

    async def build_personal_wiki(self, **_: object) -> dict[str, object]:
        """결정적인 Wiki Build 결과를 반환한다."""
        return {"wiki_version_id": "wiki-version-1", "chunk_count": 3}

    async def build_bambi_content(self, **_: object) -> dict[str, object]:
        """결정적인 Bambi 콘텐츠 저장 결과를 반환한다."""
        return {
            "content_candidate_id": "candidate-1",
            "content_id": "content-1",
            "title": "생성 제목",
        }

    async def complete_job(self, **kwargs: object) -> None:
        """완료 결과를 테스트 상태에 기록한다."""
        self.completed = kwargs["result"]  # type: ignore[assignment]

    async def fail_job(self, **kwargs: object) -> str:
        """실패 코드를 테스트 상태에 기록한다."""
        self.failed = str(kwargs["error_code"])
        return "failed"


def _fetch_url(_: str) -> JinaReadResult:
    """외부 호출 없이 결정적인 Jina 수집 결과를 반환한다."""
    return JinaReadResult(
        requested_url="https://example.com",
        resolved_url="https://example.com/article",
        title="제목",
        published_time="2026-07-16T00:00:00Z",
        markdown="# 본문",
    )


def test_run_url_job_returns_followup_wiki_job() -> None:
    """URL Job 실행이 원본 저장과 후속 Wiki Build Job ID를 반환하는지 검증한다."""
    repository = _FakeAgentRepository()
    service = AgentWorkflowService(
        repository,  # type: ignore[arg-type]
        Settings(environment="test", dev_agent_timeout_seconds=30),
        url_fetcher=_fetch_url,
    )

    response = asyncio.run(service.run_job("job-1"))

    assert response.status == "completed"
    assert response.stages[0].name == "url_collection"
    assert response.result["wiki_build_job_id"] == "wiki-job-1"
    assert repository.completed == response.result


def test_run_wiki_job_calls_personal_wiki_handler() -> None:
    """Wiki Job 실행이 증분 Builder 결과를 완료 상태로 저장하는지 검증한다."""
    repository = _FakeAgentRepository("personal_wiki_build")
    service = AgentWorkflowService(
        repository,  # type: ignore[arg-type]
        Settings(environment="test", dev_agent_timeout_seconds=30),
    )

    response = asyncio.run(
        service.run_job(
            "job-1",
            expected_job_type="personal_wiki_build",
            expected_user_id="user-1",
        )
    )

    assert response.status == "completed"
    assert response.stages[0].name == "wiki_build"
    assert response.result["wiki_version_id"] == "wiki-version-1"


def test_run_bambi_job_calls_generation_handler() -> None:
    """Bambi Job 실행이 검색·생성·영속화 Handler 결과를 완료 처리하는지 검증한다."""
    repository = _FakeAgentRepository("bambi_generation")
    service = AgentWorkflowService(
        repository,  # type: ignore[arg-type]
        Settings(environment="test", dev_agent_timeout_seconds=30),
    )

    response = asyncio.run(
        service.run_job(
            "job-1",
            expected_job_type="bambi_generation",
            expected_user_id="user-1",
        )
    )

    assert response.status == "completed"
    assert response.stages[0].name == "bambi_generation"
    assert response.result["content_candidate_id"] == "candidate-1"
    assert repository.completed == response.result
