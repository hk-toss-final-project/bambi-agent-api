"""원본에서 Bambi 콘텐츠까지 이어지는 개발 시나리오를 검증한다."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from app.schemas.development import (
    DevelopmentJobRunResponse,
    DevelopmentRunStage,
    SourceToContentScenarioRequest,
)
from app.schemas.interests import InterestProfileResponse
from app.schemas.latest_information import LatestInformationSearchResponse
from app.schemas.mvp import AcceptedJobResponse, JobStatus
from app.services.development_scenarios import DevelopmentScenarioService


class _FakeJobs:
    """시나리오의 Context·원본·생성 Job 접수 결과를 제공한다."""

    async def upsert_user_context(self, *_: object) -> SimpleNamespace:
        """반영된 Context Version을 반환한다."""
        return SimpleNamespace(context_version=1)

    async def submit_web_clipping(self, **_: object) -> AcceptedJobResponse:
        """클리핑과 함께 등록된 Wiki Build Job을 반환한다."""
        return _accepted("wiki-job-1", source=True)

    async def submit_generation(self, **_: object) -> AcceptedJobResponse:
        """등록된 Bambi 생성 Job을 반환한다."""
        return _accepted("bambi-job-1", generation=True)


class _FakeWorkflows:
    """Wiki Build와 Bambi 생성 Handler 결과를 Job ID별로 반환한다."""

    async def run_job(self, job_id: str, **_: object) -> DevelopmentJobRunResponse:
        """Job ID에 대응하는 저장 결과를 반환한다."""
        if job_id == "wiki-job-1":
            stage = "wiki_build"
            result: dict[str, object] = {"wiki_version_id": "wiki-version-1"}
            job_type = "personal_wiki_build"
        else:
            stage = "bambi_generation"
            result = {"content_candidate_id": "candidate-1"}
            job_type = "bambi_generation"
        return DevelopmentJobRunResponse(
            run_id=f"run-{job_id}",
            job_id=job_id,
            job_type=job_type,
            status="completed",
            started_at=datetime.now(UTC),
            duration_ms=1,
            stages=[
                DevelopmentRunStage(
                    name=stage,
                    status="completed",
                    duration_ms=1,
                    result=result,
                )
            ],
            result=result,
        )


class _FakeInterests:
    """활성 Wiki에서 계산된 빈 관심 Profile을 반환한다."""

    async def rebuild(self, user_id: str, *, limit: int) -> InterestProfileResponse:
        """시나리오 연결 검증용 Profile을 반환한다."""
        assert limit == 10
        return InterestProfileResponse(
            profile_id="profile-1",
            user_id=user_id,
            wiki_version_id="wiki-version-1",
            version=1,
            status="active",
            calculated_at=datetime.now(UTC),
            interests=[],
        )


class _FakeLatestInformation:
    """외부 네트워크 없이 최신 정보 검색 결과를 반환한다."""

    async def search(self, user_id: str, _: object) -> LatestInformationSearchResponse:
        """시나리오 연결 검증용 빈 최신 문서 결과를 반환한다."""
        return LatestInformationSearchResponse(
            user_id=user_id,
            query="postgresql",
            keywords=["postgresql"],
            items=[],
        )


def _accepted(
    job_id: str, *, source: bool = False, generation: bool = False
) -> AcceptedJobResponse:
    """접수 유형에 필요한 식별자를 포함한 공통 202 응답을 만든다."""
    return AcceptedJobResponse(
        job_id=job_id,
        feature_id="SVC-002" if source else "SVC-008",
        status=JobStatus.QUEUED,
        request_id="request-1",
        created_at=datetime.now(UTC),
        source_document_id="source-1" if source else None,
        source_document_version_id="source-version-1" if source else None,
        generation_request_id="generation-request-1" if generation else None,
    )


def test_source_to_content_scenario_returns_all_persisted_stage_ids() -> None:
    """클리핑·Wiki·관심·최신 정보·Bambi 결과 ID가 한 응답에 모이는지 검증한다."""
    payload = SourceToContentScenarioRequest.model_validate(
        {
            "context": {"context_version": 1, "plan": "free"},
            "source": {
                "type": "clipping",
                "source_event_id": "clip-1",
                "source": "https://example.com/article",
                "title": "데이터베이스 버전 관리",
                "content": "# 본문\n버전 테이블을 사용한다.",
            },
            "interest_limit": 10,
            "latest": {"keywords": ["postgresql"], "providers": ["gdelt"]},
            "generation": {
                "idempotency_key": "generation-1",
                "topic": "PostgreSQL 버전 관리",
            },
        }
    )
    service = DevelopmentScenarioService(
        _FakeJobs(),  # type: ignore[arg-type]
        _FakeWorkflows(),  # type: ignore[arg-type]
        _FakeInterests(),  # type: ignore[arg-type]
        _FakeLatestInformation(),  # type: ignore[arg-type]
    )

    response = asyncio.run(service.run("user-1", payload, request_id="request-1"))

    assert response.status == "completed"
    assert [stage.name for stage in response.stages] == [
        "context",
        "source_ingestion",
        "wiki_build",
        "interest_extraction",
        "latest_collection",
        "bambi_generation",
    ]
    assert response.result["source_document_version_id"] == "source-version-1"
    assert response.result["wiki_version_id"] == "wiki-version-1"
    assert response.result["interest_profile_id"] == "profile-1"
    assert response.result["content_candidate_id"] == "candidate-1"
