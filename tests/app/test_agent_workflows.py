"""개발 API와 Worker가 공유하는 Agent Job 실행기를 검증한다."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.services.agent_jobs import AgentJobRecord, ClaimedJobRecord
from app.services.agent_workflows import AgentWorkflowService
from infrastructure.sources.connectors.api import JinaReadResult


class _RecordingRunner:
    """그래프 실행 인자를 기록하고 고정 결과를 반환하는 러너 대역."""

    def __init__(self, result: dict[str, object]) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, connection: Any, **kwargs: Any) -> dict[str, object]:
        """호출 연결과 키워드 인자를 기록하고 고정 결과를 반환한다."""
        self.calls.append({"connection": connection, **kwargs})
        return dict(self._result)


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
        if self.record.job_type == "personal_wiki_url":
            payload: dict[str, object] = {
                "url": "https://example.com",
                "source_document_id": "source-1",
                "source_event_id": "event-1",
                "source_event_row_id": "event-row-1",
            }
        elif self.record.job_type == "report_generation":
            payload = {
                "topic": "개인화",
                "content_type": "article",
                "language": "ko",
            }
        else:
            payload = {"source_document_version_id": "source-version-1"}
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

    @asynccontextmanager
    async def acquire_connection(self) -> AsyncIterator[object]:
        """그래프 실행에 빌려줄 연결 대역을 반환한다."""
        yield "fake-connection"

    async def complete_job(self, **kwargs: object) -> None:
        """완료 결과를 테스트 상태에 기록한다."""
        self.completed = kwargs["result"]  # type: ignore[assignment]

    async def fail_job(self, **kwargs: object) -> str:
        """실패 코드를 테스트 상태에 기록한다."""
        self.failed = str(kwargs["error_code"])
        return "failed"


class _FullRebuildRepository(_FakeAgentRepository):
    """북마크 해제용 full_rebuild Payload를 반환하는 저장소 대역."""

    def __init__(self) -> None:
        """Personal Wiki Build Job으로 초기화한다."""
        super().__init__("personal_wiki_build")

    async def claim_job(
        self, *, job_id: str, worker_id: str, lease_seconds: int
    ) -> ClaimedJobRecord | None:
        """원본 Version 없이 전체 재구성 모드로 점유한다."""
        return ClaimedJobRecord(
            job_id=job_id,
            user_id="user-1",
            feature_id="SVC-004",
            job_type="personal_wiki_build",
            attempt_number=1,
            max_attempts=3,
            payload={"mode": "full_rebuild"},
        )


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


def test_run_wiki_job_invokes_wiki_graph_runner() -> None:
    """Wiki Job 실행이 빌린 연결로 그래프 러너를 호출하고 완료 저장하는지 검증한다."""
    repository = _FakeAgentRepository("personal_wiki_build")
    runner = _RecordingRunner({"wiki_version_id": "wiki-version-1", "chunk_count": 3})
    service = AgentWorkflowService(
        repository,  # type: ignore[arg-type]
        Settings(environment="test", dev_agent_timeout_seconds=30),
        wiki_runner=runner,
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
    call = runner.calls[0]
    assert call["connection"] == "fake-connection"
    assert call["source_document_version_id"] == "source-version-1"
    assert call["user_id"] == "user-1"
    assert call["job_id"] == "job-1"


def test_run_full_rebuild_job_uses_rebuild_runner_without_source_version() -> None:
    """북마크 해제 Job은 단일 원본 ID 없이 전체 재구성 러너를 호출한다."""
    repository = _FullRebuildRepository()
    runner = _RecordingRunner({"full_rebuild": True, "source_count": 1})
    service = AgentWorkflowService(
        repository,  # type: ignore[arg-type]
        Settings(environment="test", dev_agent_timeout_seconds=30),
        wiki_rebuild_runner=runner,
    )

    response = asyncio.run(service.run_job("job-1"))

    assert response.status == "completed"
    assert response.stages[0].name == "wiki_rebuild"
    assert runner.calls[0]["user_id"] == "user-1"
    assert "source_document_version_id" not in runner.calls[0]


def test_run_report_job_invokes_generation_graph_runner() -> None:
    """Report Builder Job 실행이 Payload 인자로 생성 그래프를 호출하고 완료 처리하는지 검증한다."""
    repository = _FakeAgentRepository("report_generation")
    runner = _RecordingRunner(
        {
            "content_candidate_id": "candidate-1",
            "content_id": "content-1",
            "title": "생성 제목",
        }
    )
    service = AgentWorkflowService(
        repository,  # type: ignore[arg-type]
        Settings(environment="test", dev_agent_timeout_seconds=30),
        report_runner=runner,
    )

    response = asyncio.run(
        service.run_job(
            "job-1",
            expected_job_type="report_generation",
            expected_user_id="user-1",
        )
    )

    assert response.status == "completed"
    assert response.stages[0].name == "report_generation"
    assert response.result["content_candidate_id"] == "candidate-1"
    assert repository.completed == response.result
    call = runner.calls[0]
    assert call["topic"] == "개인화"
    assert call["content_type"] == "article"
    assert call["attempt_number"] == 1
    assert call["generation_scope"] == "SINGLE_TOPIC"
    assert call["interest_bundle"] is None


def test_development_workflow_passes_interest_bundle_snapshot() -> None:
    """개발 즉시 실행 경로도 운영 Worker와 같은 관심사 묶음 스냅샷을 사용한다."""
    bundle = {
        "root": {"keyword": "생성형 AI"},
        "neighbors": [{"keyword": "AI 에이전트"}],
        "keywords": ["생성형 AI", "AI 에이전트"],
    }

    class _BundleRepository(_FakeAgentRepository):
        """범주 리포트 Job payload를 반환하는 저장소 대역."""

        async def claim_job(
            self, *, job_id: str, worker_id: str, lease_seconds: int
        ) -> ClaimedJobRecord | None:
            """기본 점유 결과의 payload를 관심사 묶음 요청으로 바꾼다."""
            claimed = await super().claim_job(
                job_id=job_id, worker_id=worker_id, lease_seconds=lease_seconds
            )
            assert claimed is not None
            return replace(
                claimed,
                payload={
                    "topic": "생성형 AI",
                    "content_type": "interest_news_card",
                    "language": "ko",
                    "generation_scope": "INTEREST_BUNDLE",
                    "interest_bundle": bundle,
                },
            )

    repository = _BundleRepository("report_generation")
    runner = _RecordingRunner({"content_candidate_id": "candidate-1"})
    service = AgentWorkflowService(
        repository,  # type: ignore[arg-type]
        Settings(environment="test", dev_agent_timeout_seconds=30),
        report_runner=runner,
    )

    response = asyncio.run(service.run_job("job-1"))

    assert response.status == "completed"
    assert runner.calls[0]["generation_scope"] == "INTEREST_BUNDLE"
    assert runner.calls[0]["interest_bundle"] == bundle


class _FakeBatchRepository(_FakeAgentRepository):
    """대기 Job 두 개 중 하나만 점유를 허용하는 Batch Repository 대역."""

    def __init__(self) -> None:
        """Wiki Build Job 두 개와 목록 조회 조건 기록을 준비한다."""
        super().__init__("personal_wiki_build")
        self.listed: tuple[str, str | None, int] | None = None

    async def list_runnable_jobs(
        self, *, job_type: str, user_id: str | None = None, limit: int
    ) -> list[str]:
        """조회 조건을 기록하고 고정 Job ID 두 개를 반환한다."""
        self.listed = (job_type, user_id, limit)
        return ["job-1", "job-2"]

    async def get_job(self, job_id: str) -> AgentJobRecord | None:
        """두 Job 모두 실행 대기 상태 레코드를 반환한다."""
        if job_id in {"job-1", "job-2"}:
            return replace(self.record, job_id=job_id)
        return None

    async def claim_job(
        self, *, job_id: str, worker_id: str, lease_seconds: int
    ) -> ClaimedJobRecord | None:
        """job-1만 점유를 허용하고 job-2는 경합 상태로 만든다."""
        if job_id != "job-1":
            return None
        return await super().claim_job(
            job_id=job_id, worker_id=worker_id, lease_seconds=lease_seconds
        )


def test_run_pending_jobs_aggregates_batch_results() -> None:
    """대기 Job Batch 실행이 완료와 건너뜀을 항목별로 집계하는지 검증한다."""
    repository = _FakeBatchRepository()
    service = AgentWorkflowService(
        repository,  # type: ignore[arg-type]
        Settings(environment="test", dev_agent_timeout_seconds=30),
        wiki_runner=_RecordingRunner(
            {"wiki_version_id": "wiki-version-1", "chunk_count": 3}
        ),
    )

    response = asyncio.run(
        service.run_pending_jobs(
            job_type="personal_wiki_build", user_id="user-1", limit=5
        )
    )

    assert repository.listed == ("personal_wiki_build", "user-1", 5)
    assert response.job_type == "personal_wiki_build"
    assert response.pending_count == 2
    assert response.completed_count == 1
    assert response.failed_count == 0
    assert response.skipped_count == 1
    assert response.items[0].status == "completed"
    assert response.items[0].run is not None
    assert response.items[0].run.result["wiki_version_id"] == "wiki-version-1"
    assert response.items[1].status == "skipped"
    assert response.items[1].error_code == "JOB_NOT_RUNNABLE"
    assert response.items[1].run is None
