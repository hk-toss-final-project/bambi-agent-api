"""Service API 연동 FastAPI MVP 엔드포인트를 검증한다."""

from fastapi.testclient import TestClient

from tests.conftest import InMemoryAgentJobRepository


def _put_context(client: TestClient, user_id: str, version: int = 1) -> None:
    """생성 요청의 전제인 사용자 컨텍스트를 등록한다."""
    response = client.put(
        f"/internal/v1/users/{user_id}/context",
        json={"context_version": version, "plan": "free"},
    )
    assert response.status_code == 200


def test_user_context_upsert_rejects_stale_version(client: TestClient) -> None:
    """사용자 컨텍스트가 최신 버전만 반영하고 오래된 요청을 거절하는지 검증한다."""
    payload = {
        "context_version": 1,
        "plan": "paid",
        "preferred_language": "ko",
        "personalization_enabled": True,
        "blocked_interest_ids": ["blocked-interest"],
        "blocked_source_ids": ["blocked-source"],
    }

    first = client.put("/internal/v1/users/user-1/context", json=payload)
    stale = client.put("/internal/v1/users/user-1/context", json=payload)

    assert first.status_code == 200
    assert first.json()["feature_id"] == "SVC-001"
    assert first.json()["context_version"] == 1
    assert stale.status_code == 409
    assert stale.json()["code"] == "STALE_CONTEXT_VERSION"


def test_web_clipping_request_is_idempotent(client: TestClient) -> None:
    """같은 Source Event로 요청한 웹 클리핑이 하나의 Job으로 접수되는지 검증한다."""
    payload = {
        "source_event_id": "clip-event-1",
        "url": "https://example.com/article",
        "title": "Example Article",
        "content": "Article body",
    }

    first = client.post(
        "/internal/v1/users/user-1/wiki-sources/clippings", json=payload
    )
    duplicate = client.post(
        "/internal/v1/users/user-1/wiki-sources/clippings", json=payload
    )
    status_response = client.get(f"/internal/v1/jobs/{first.json()['job_id']}")

    assert first.status_code == 202
    assert duplicate.status_code == 202
    assert first.json()["job_id"] == duplicate.json()["job_id"]
    assert first.json()["feature_id"] == "SVC-002"
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "queued"


def test_generation_job_result_flow(
    client: TestClient, agent_jobs_fake: InMemoryAgentJobRepository
) -> None:
    """생성 Job이 접수되고 완료 전후의 결과 조회 상태가 달라지는지 검증한다."""
    _put_context(client, "user-2")
    accepted = client.post(
        "/internal/v1/users/user-2/generations",
        json={
            "idempotency_key": "generation-1",
            "topic": "AI agent trends",
            "content_type": "interest_news_card",
        },
    )
    job_id = accepted.json()["job_id"]
    pending = client.get(f"/internal/v1/jobs/{job_id}/result")
    agent_jobs_fake.finish_job(job_id, {"content_id": "content-1"})
    completed = client.get(f"/internal/v1/jobs/{job_id}/result")

    assert accepted.status_code == 202
    assert accepted.json()["feature_id"] == "SVC-008"
    assert pending.status_code == 409
    assert pending.json()["code"] == "JOB_RESULT_NOT_READY"
    assert completed.status_code == 200
    assert completed.json()["result"] == {"content_id": "content-1"}


def test_content_mark_returns_not_implemented(client: TestClient) -> None:
    """위키마킹 접수가 Handler 구현 전까지 명시적 501을 반환하는지 검증한다."""
    response = client.post(
        "/internal/v1/users/user-1/wiki-sources/content-marks",
        json={"source_event_id": "mark-1", "content_id": "content-1"},
    )

    assert response.status_code == 501
    assert response.json()["code"] == "NOT_IMPLEMENTED"


def test_generation_requires_user_context(client: TestClient) -> None:
    """컨텍스트가 없는 사용자의 생성 요청은 409로 거부되는지 검증한다."""
    rejected = client.post(
        "/internal/v1/users/no-context-user/generations",
        json={
            "idempotency_key": "generation-no-context",
            "topic": "AI agent trends",
        },
    )

    assert rejected.status_code == 409
    assert rejected.json()["code"] == "USER_CONTEXT_REQUIRED"


def test_generation_request_accepts_scheduled_time(client: TestClient) -> None:
    """시간대를 포함한 예약 시각의 생성 요청이 정상 접수되는지 검증한다."""
    _put_context(client, "user-3")
    accepted = client.post(
        "/internal/v1/users/user-3/generations",
        json={
            "idempotency_key": "2026-07-21-user-3-interest_news_card",
            "topic": "AI agent trends",
            "scheduled_at": "2026-07-21T07:00:00+09:00",
        },
    )

    assert accepted.status_code == 202
    assert accepted.json()["feature_id"] == "SVC-008"


def test_generation_request_rejects_naive_scheduled_time(client: TestClient) -> None:
    """시간대 없는 예약 시각은 모호하므로 422 검증 오류를 반환한다."""
    rejected = client.post(
        "/internal/v1/users/user-3/generations",
        json={
            "idempotency_key": "generation-naive",
            "topic": "AI agent trends",
            "scheduled_at": "2026-07-21T07:00:00",
        },
    )

    assert rejected.status_code == 422
    assert rejected.json()["code"] == "REQUEST_VALIDATION_ERROR"


def test_unknown_job_returns_not_found(client: TestClient) -> None:
    """존재하지 않는 Agent Job 조회가 404 공통 오류를 반환하는지 검증한다."""
    response = client.get("/internal/v1/jobs/unknown-job")

    assert response.status_code == 404
    assert response.json()["code"] == "JOB_NOT_FOUND"
