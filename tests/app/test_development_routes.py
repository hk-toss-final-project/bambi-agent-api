"""환경으로 제한된 개발용 Agent 실행 라우터를 검증한다."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import AppContainer, create_container
from app.main import create_app
from app.schemas.development import DevelopmentJobRunResponse, DevelopmentRunStage


class _FakeWorkflowService:
    """개발 라우터 호출 인자를 기록하고 고정 실행 결과를 반환한다."""

    def __init__(self) -> None:
        """아직 호출되지 않은 초기 상태를 준비한다."""
        self.called: tuple[str, str | None, str | None] | None = None

    async def run_job(
        self,
        job_id: str,
        *,
        expected_job_type: str | None = None,
        expected_user_id: str | None = None,
    ) -> DevelopmentJobRunResponse:
        """호출 조건을 기록하고 완료 결과를 반환한다."""
        self.called = (job_id, expected_job_type, expected_user_id)
        return DevelopmentJobRunResponse(
            run_id="run-1",
            job_id=job_id,
            job_type=expected_job_type or "personal_wiki_url",
            status="completed",
            started_at=datetime.now(UTC),
            duration_ms=1,
            stages=[
                DevelopmentRunStage(
                    name="wiki_build",
                    status="completed",
                    duration_ms=1,
                )
            ],
            result={"wiki_version_id": "wiki-version-1"},
        )


def _development_client(
    *, token: str | None = None
) -> tuple[TestClient, AppContainer, _FakeWorkflowService]:
    """개발 라우터와 가짜 실행기가 연결된 TestClient를 만든다."""
    settings = Settings(
        environment="test",
        enable_dev_agent_api=True,
        dev_agent_api_token=token,
    )
    container = create_container(settings)
    workflow = _FakeWorkflowService()
    container.agent_workflow_service = workflow  # type: ignore[assignment]
    return TestClient(create_app(settings, container)), container, workflow


def test_development_routes_are_absent_without_explicit_flag() -> None:
    """개발 API 플래그가 없으면 Route와 OpenAPI Tag가 등록되지 않는지 검증한다."""
    application = create_app(Settings(environment="test"))
    with TestClient(application) as client:
        response = client.post("/internal/v1/dev/jobs/job-1/run")
        tags = {tag["name"] for tag in client.get("/openapi.json").json()["tags"]}

    assert response.status_code == 404
    assert "dev-jobs" not in tags


def test_development_job_and_wiki_routes_call_workflow() -> None:
    """개발 Job·Wiki 경로가 공통 실행기를 올바른 제약으로 호출하는지 검증한다."""
    client, _, workflow = _development_client()
    with client:
        job_response = client.post("/internal/v1/dev/jobs/job-1/run")
        wiki_response = client.post(
            "/internal/v1/dev/users/user-1/wiki-builds",
            json={"job_id": "wiki-job-1"},
        )

    assert job_response.status_code == 200
    assert wiki_response.status_code == 200
    assert workflow.called == ("wiki-job-1", "personal_wiki_build", "user-1")


def test_development_route_requires_configured_token() -> None:
    """설정에 토큰이 있으면 일치하는 X-Dev-Token만 허용하는지 검증한다."""
    client, _, _ = _development_client(token="secret-token")
    with client:
        rejected = client.post("/internal/v1/dev/jobs/job-1/run")
        accepted = client.post(
            "/internal/v1/dev/jobs/job-1/run",
            headers={"X-Dev-Token": "secret-token"},
        )

    assert rejected.status_code == 401
    assert rejected.json()["code"] == "INVALID_DEV_TOKEN"
    assert accepted.status_code == 200
