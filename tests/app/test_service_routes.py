"""Service API 연동 FastAPI MVP 엔드포인트를 검증한다."""

from fastapi.testclient import TestClient

from tests.conftest import InMemoryAgentJobRepository


def _taxonomy_payload() -> dict[str, object]:
    """Service가 보내는 최소 taxonomy Snapshot 요청을 만든다."""
    return {
        "version": "1.0.0",
        "source_hash": "a" * 64,
        "locale": "ko-KR",
        "categories": [
            {
                "id": "technology",
                "name": "기술",
                "name_en": "Technology",
                "description": "기술 설명",
                "emoji": "💻",
                "order": 1,
                "topics": [
                    {
                        "id": "generative_ai",
                        "name": "생성형 AI",
                        "name_en": "Generative AI",
                        "description": "생성형 AI 설명",
                        "order": 1,
                        "keywords": ["LLM"],
                    }
                ],
            }
        ],
    }


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
    # 현재 버전을 함께 알려준다. Service는 자기 카운터로 버전을 매기는데 그
    # 카운터가 Agent와 독립이라, 이 값이 없으면 무엇을 보내야 통과하는지 알 수
    # 없다(2026-08-06: 이 409를 삼켜 온보딩 관심사 전달이 조용히 막혔다).
    assert stale.json()["details"] == [{"current_context_version": 1}]


def test_interest_taxonomy_upsert_is_idempotent(client: TestClient) -> None:
    """같은 버전·Hash의 taxonomy Snapshot을 반복 동기화할 수 있는지 검증한다."""
    payload = _taxonomy_payload()

    first = client.put("/internal/v1/interest-taxonomies/1.0.0", json=payload)
    duplicate = client.put("/internal/v1/interest-taxonomies/1.0.0", json=payload)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert first.json() == {
        "version": "1.0.0",
        "source_hash": "a" * 64,
        "category_count": 1,
        "topic_count": 1,
    }


def test_interest_taxonomy_rejects_path_version_mismatch(client: TestClient) -> None:
    """경로와 본문 taxonomy 버전이 다르면 Snapshot을 저장하지 않는다."""
    response = client.put(
        "/internal/v1/interest-taxonomies/2.0.0", json=_taxonomy_payload()
    )

    assert response.status_code == 409
    assert response.json()["code"] == "INTEREST_TAXONOMY_VERSION_MISMATCH"


def test_user_context_upsert_preserves_signup_interests(
    client: TestClient, agent_jobs_fake: InMemoryAgentJobRepository
) -> None:
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
    assert len(agent_jobs_fake.jobs_with_feature("SVC-008")) == 2


def test_user_context_accepts_custom_topic_without_category(client: TestClient) -> None:
    """사용자 추가 Topic은 Category null 상태로 Snapshot에 보존되는지 검증한다."""
    response = client.put(
        "/internal/v1/users/custom-topic-user/context",
        json={
            "context_version": 1,
            "plan": "free",
            "signup_interests": [{"category": None, "topics": ["양자 센서"]}],
        },
    )

    assert response.status_code == 200
    assert response.json()["signup_interests"] == [
        {"category": None, "topics": ["양자 센서"]}
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


def test_onboarding_with_interests_enqueues_seed_job(
    client: TestClient, agent_jobs_fake: InMemoryAgentJobRepository
) -> None:
    """signup_interests가 있으면 온보딩 관심사 시드(WSE-014) Build Job이 접수되는지 검증한다."""
    response = client.put(
        "/internal/v1/users/seed-user/context",
        json={
            "context_version": 1,
            "plan": "free",
            "signup_interests": [{"category": "기술", "topics": ["AI"]}],
        },
    )

    assert response.status_code == 200
    seed_jobs = agent_jobs_fake.jobs_with_feature("WSE-014")
    assert len(seed_jobs) == 1
    assert seed_jobs[0].job_type == "personal_wiki_build"
    report_jobs = agent_jobs_fake.jobs_with_feature("SVC-008")
    assert len(report_jobs) == 1
    assert report_jobs[0].idempotency_key.startswith("interest-report:")


def test_onboarding_without_interests_skips_seed_job(
    client: TestClient, agent_jobs_fake: InMemoryAgentJobRepository
) -> None:
    """signup_interests가 없으면 시드 Job을 접수하지 않는지 검증한다."""
    response = client.put(
        "/internal/v1/users/no-seed-user/context",
        json={"context_version": 1, "plan": "free"},
    )

    assert response.status_code == 200
    assert agent_jobs_fake.jobs_with_feature("WSE-014") == []


def test_onboarding_seed_failure_does_not_break_context(
    client: TestClient, agent_jobs_fake: InMemoryAgentJobRepository
) -> None:
    """시드 접수가 실패해도 컨텍스트 저장(200)은 유지되는지 검증한다."""

    async def _raise(**_: object) -> None:
        raise RuntimeError("시드 저장소 장애")

    agent_jobs_fake.submit_onboarding_seed = _raise  # type: ignore[method-assign]

    response = client.put(
        "/internal/v1/users/seed-fail-user/context",
        json={
            "context_version": 1,
            "plan": "free",
            "signup_interests": [{"category": "경제", "topics": ["금리"]}],
        },
    )

    assert response.status_code == 200
    assert response.json()["signup_interests"] == [{"category": "경제", "topics": ["금리"]}]


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


def test_job_status_batch_preserves_order_and_reports_missing_jobs(
    client: TestClient,
) -> None:
    """Batch 상태 조회가 요청 순서를 지키고 없는 Job을 분리하는지 검증한다."""
    first = client.post(
        "/internal/v1/users/user-1/wiki-sources/clippings",
        json={
            "source_event_id": "clip-batch-1",
            "url": "https://example.com/one",
            "title": "첫 번째",
            "content": "첫 번째 본문",
        },
    ).json()["job_id"]
    second = client.post(
        "/internal/v1/users/user-1/wiki-sources/clippings",
        json={
            "source_event_id": "clip-batch-2",
            "url": "https://example.com/two",
            "title": "두 번째",
            "content": "두 번째 본문",
        },
    ).json()["job_id"]
    missing = "00000000-0000-0000-0000-000000000000"

    response = client.post(
        "/internal/v1/jobs/statuses",
        json={"job_ids": [second, missing, first]},
    )

    assert response.status_code == 200
    assert [item["job_id"] for item in response.json()["items"]] == [second, first]
    assert response.json()["missing_job_ids"] == [missing]


def test_job_status_batch_rejects_duplicate_ids(client: TestClient) -> None:
    """같은 Job ID를 한 Batch에 두 번 넣으면 입력 오류로 거절하는지 검증한다."""
    job_id = "00000000-0000-0000-0000-000000000001"

    response = client.post(
        "/internal/v1/jobs/statuses",
        json={"job_ids": [job_id, job_id]},
    )

    assert response.status_code == 422


def test_generation_request_forwards_report_type_to_the_repository(
    client: TestClient, agent_jobs_fake: InMemoryAgentJobRepository
) -> None:
    """요청의 report_type이 저장소까지 그대로 전달된다.

    Agent는 이 값을 해석하지 않고 발행 Snapshot에 실어 돌려주기만 한다.
    값의 정의는 Service가 소유한다(2026-08-06 이송우 협의).
    """
    _put_context(client, "user-2")

    accepted = client.post(
        "/internal/v1/users/user-2/generations",
        json={
            "idempotency_key": "generation-report-type",
            "topic": "AI agent trends",
            "content_type": "interest_news_card",
            "report_type": "MORNING_BRIEFING",
        },
    )

    assert accepted.status_code == 202
    assert agent_jobs_fake.last_report_type == "MORNING_BRIEFING"


def test_generation_request_allows_omitting_report_type(
    client: TestClient, agent_jobs_fake: InMemoryAgentJobRepository
) -> None:
    """report_type을 보내지 않던 기존 호출도 그대로 접수된다."""
    _put_context(client, "user-2")

    accepted = client.post(
        "/internal/v1/users/user-2/generations",
        json={
            "idempotency_key": "generation-no-report-type",
            "topic": "AI agent trends",
        },
    )

    assert accepted.status_code == 202
    assert agent_jobs_fake.last_report_type == ""


def test_generation_request_forwards_interest_bundle_scope(
    client: TestClient, agent_jobs_fake: InMemoryAgentJobRepository
) -> None:
    """범주 리포트는 topic 없이 활성 관심사 ID를 저장소까지 전달한다."""
    _put_context(client, "user-bundle")

    accepted = client.post(
        "/internal/v1/users/user-bundle/generations",
        json={
            "idempotency_key": "generation-interest-bundle",
            "generation_scope": "INTEREST_BUNDLE",
            "interest_id": "33333333-3333-4333-8333-333333333333",
        },
    )

    assert accepted.status_code == 202
    assert agent_jobs_fake.last_generation_scope == "INTEREST_BUNDLE"
    assert agent_jobs_fake.last_interest_id == "33333333-3333-4333-8333-333333333333"


def test_generation_request_requires_interest_id_for_bundle(client: TestClient) -> None:
    """범주 리포트에 활성 관심사 ID가 없으면 요청 검증 단계에서 거부한다."""
    rejected = client.post(
        "/internal/v1/users/user-bundle/generations",
        json={
            "idempotency_key": "generation-interest-bundle-no-interest",
            "generation_scope": "INTEREST_BUNDLE",
        },
    )

    assert rejected.status_code == 422
    assert rejected.json()["code"] == "REQUEST_VALIDATION_ERROR"


def test_generation_request_rejects_topics_mixed_with_bundle(client: TestClient) -> None:
    """Wiki 연결 노드 묶음과 호출자가 지정한 topics를 한 요청에서 섞지 않는다."""
    rejected = client.post(
        "/internal/v1/users/user-bundle/generations",
        json={
            "idempotency_key": "generation-interest-bundle-mixed",
            "generation_scope": "INTEREST_BUNDLE",
            "interest_id": "33333333-3333-4333-8333-333333333333",
            "topics": ["호출자 지정 키워드"],
        },
    )

    assert rejected.status_code == 422
    assert rejected.json()["code"] == "REQUEST_VALIDATION_ERROR"


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


def test_feedback_signals_accepts_batch_idempotently(
    client: TestClient,
    agent_jobs_fake: InMemoryAgentJobRepository,
) -> None:
    """행동 신호와 계측값을 보존하고 같은 이벤트 재전송은 제외한다."""
    payload = {
        "signals": [
            {
                "source_event_id": "signal-1",
                "signal_type": "like",
                "topics": ["LangGraph"],
                "content_id": "content-1",
                "metadata": {
                    "axis": "topic",
                    "dwell_seconds": 1.8,
                    "scroll_ratio": 0.0,
                    "source": {"surface": "report"},
                },
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
    assert agent_jobs_fake.feedback_signals[0]["metadata"] == {
        "axis": "topic",
        "dwell_seconds": 1.8,
        "scroll_ratio": 0.0,
        "source": {"surface": "report"},
    }


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
