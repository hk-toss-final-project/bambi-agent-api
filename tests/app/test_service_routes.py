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
        "interest_taxonomy_version": "1.0.0",
        "selected_category_ids": ["tech", "business"],
        "selected_topic_ids": ["ai_ml", "startup"],
        "blocked_interest_ids": ["blocked-interest"],
        "blocked_source_ids": ["blocked-source"],
    }

    first = client.put("/internal/v1/users/user-1/context", json=payload)
    stale = client.put("/internal/v1/users/user-1/context", json=payload)

    assert first.status_code == 200
    assert first.json()["feature_id"] == "SVC-001"
    assert first.json()["context_version"] == 1
    assert first.json()["interest_taxonomy_version"] == "1.0.0"
    assert first.json()["selected_category_ids"] == ["tech", "business"]
    assert first.json()["selected_topic_ids"] == ["ai_ml", "startup"]
    assert stale.status_code == 409
    assert stale.json()["code"] == "STALE_CONTEXT_VERSION"


def test_user_context_upsert_preserves_signup_interests(client: TestClient) -> None:
    """회원가입 시 고른 관심 카테고리·토픽이 컨텍스트 응답에 그대로 반영되는지 검증한다."""
    payload = {
        "context_version": 1,
        "plan": "free",
        "signup_interests": [
            {"category": "기술", "topics": ["AI", "반도체"]},
            {"category": "경제", "topics": []},
        ],
    }

    response = client.put("/internal/v1/users/signup-user/context", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["signup_interests"] == [
        {"category": "기술", "topics": ["AI", "반도체"]},
        {"category": "경제", "topics": []},
    ]


def test_user_context_upsert_defaults_signup_interests_to_empty(
    client: TestClient,
) -> None:
    """signup_interests를 생략해도 기존 계약대로 빈 목록으로 처리되는지 검증한다."""
    response = client.put(
        "/internal/v1/users/no-interest-user/context",
        json={"context_version": 1, "plan": "free"},
    )

    assert response.status_code == 200
    assert response.json()["signup_interests"] == []


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


def test_content_mark_enqueues_wiki_build_job(
    client: TestClient, agent_jobs_fake: InMemoryAgentJobRepository
) -> None:
    """위키마킹이 생성 콘텐츠를 Wiki Build Job으로 멱등 접수하는지 검증한다."""
    agent_jobs_fake.register_generated_content("user-1", "content-1")
    payload = {"source_event_id": "mark-1", "content_id": "content-1"}

    first = client.post(
        "/internal/v1/users/user-1/wiki-sources/content-marks", json=payload
    )
    duplicate = client.post(
        "/internal/v1/users/user-1/wiki-sources/content-marks", json=payload
    )

    assert first.status_code == 202
    assert first.json()["feature_id"] == "SVC-004"
    assert first.json()["source_document_version_id"] is not None
    assert duplicate.status_code == 202
    assert first.json()["job_id"] == duplicate.json()["job_id"]


def test_content_mark_rejects_unknown_generated_content(client: TestClient) -> None:
    """존재하지 않는 생성 콘텐츠 위키마킹이 404를 반환하는지 검증한다."""
    response = client.post(
        "/internal/v1/users/user-1/wiki-sources/content-marks",
        json={"source_event_id": "mark-unknown", "content_id": "missing-content"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "GENERATED_CONTENT_NOT_FOUND"


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


def test_interest_rebuild_returns_new_active_profile(
    client: TestClient, container
) -> None:
    """수동 재계산 요청이 새 활성 관심 Profile을 반환하는지 검증한다."""
    from datetime import UTC, datetime

    from app.services.interests import InterestService

    class _FakeInterestRepository:
        """활성 Wiki 한 건으로 재계산이 성공하는 저장소 대역."""

        async def load_interest_documents(self, user_id: str) -> dict:
            """관심사 계산에 쓸 활성 Wiki 문서 한 건을 반환한다."""
            return {
                "wiki_version_id": "wiki-version-1",
                "documents": [
                    {
                        "document_id": "document-1",
                        "title": "LangGraph",
                        "summary": "그래프 오케스트레이션",
                        "domain": "technology",
                        "source_metadata": {"tags": ["Python"]},
                    }
                ],
            }

        async def save_interest_profile(
            self, user_id: str, *, wiki_version_id: str, candidates
        ) -> dict:
            """계산된 후보를 활성 Profile 응답 형태로 반환한다."""
            return {
                "profile_id": "profile-1",
                "user_id": user_id,
                "wiki_version_id": wiki_version_id,
                "version": 2,
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
                    for candidate in candidates
                ],
            }

        async def list_interests(self, user_id: str) -> dict | None:
            """활성 Profile 조회는 이 테스트에서 사용하지 않는다."""
            return None

        async def load_recent_feedback_signals(self, user_id: str) -> list:
            """행동 신호가 없는 상태를 반환한다."""
            return []

    container.interest_service = InterestService(_FakeInterestRepository())

    response = client.post(
        "/internal/v1/users/user-1/interest-profiles/rebuild",
        json={"limit": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 2
    assert body["status"] == "active"
    assert body["interests"][0]["topic"] == "LangGraph"


def test_interest_rebuild_requires_ready_service(client: TestClient) -> None:
    """관심 Profile 저장소가 준비되지 않으면 503을 반환하는지 검증한다."""
    response = client.post(
        "/internal/v1/users/user-1/interest-profiles/rebuild",
        json={},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_NOT_READY"


def test_feedback_signals_accepts_batch_idempotently(client: TestClient) -> None:
    """행동 신호 Batch가 저장되고 같은 이벤트 재전송은 집계에서 빠지는지 검증한다."""
    payload = {
        "signals": [
            {
                "source_event_id": "signal-1",
                "signal_type": "like",
                "topics": ["LangGraph"],
                "content_id": "content-1",
            },
            {
                "source_event_id": "signal-2",
                "signal_type": "hide",
                "topics": ["Crypto"],
            },
        ]
    }

    first = client.post("/internal/v1/users/user-1/feedback-signals", json=payload)
    duplicate = client.post(
        "/internal/v1/users/user-1/feedback-signals", json=payload
    )

    assert first.status_code == 200
    assert first.json()["accepted_count"] == 2
    assert duplicate.status_code == 200
    assert duplicate.json()["accepted_count"] == 0


def test_feedback_signals_rejects_unknown_type(client: TestClient) -> None:
    """정의되지 않은 신호 유형이 422 검증 오류를 반환하는지 검증한다."""
    response = client.post(
        "/internal/v1/users/user-1/feedback-signals",
        json={
            "signals": [
                {
                    "source_event_id": "signal-x",
                    "signal_type": "view",
                    "topics": ["LangGraph"],
                }
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_VALIDATION_ERROR"
