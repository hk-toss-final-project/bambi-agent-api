"""Report Builder Generation Job 등록의 예약 시각(scheduled_at) 영속화를 검증한다."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any

import pytest

from infrastructure.persistence.features import generation_runtime

from infrastructure.persistence.features.generation_runtime import (
    enqueue_report_generation_job,
    load_personal_wiki_vector_context,
    load_pinned_wiki_context,
    persist_report_generation,
    persist_report_navigation_snapshot,
    upsert_user_context_snapshot,
)
from shared.report_models import GeneratedReportContent, ReportContextDocument
from shared.wiki_navigation_models import (
    WikiNavigationPacket,
    WikiNavigationPage,
    WikiNavigationSource,
)


class _FakeCursor:
    """fetchone·fetchall을 지원하는 결정적 Cursor Test Double."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        """첫 번째 Row나 None을 반환한다."""
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        """전체 Row 목록을 반환한다."""
        return self._rows


class _FakeConnection:
    """SQL 실행 내역과 순서별 응답을 기록하는 Connection Test Double."""

    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        self._responses = responses
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    async def execute(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> _FakeCursor:
        """SQL을 기록하고 순서별 고정 Cursor를 반환한다.

        실제 psycopg처럼 자리표시자 수와 파라미터 수가 어긋나면 즉시 실패시킨다.
        컬럼만 추가하고 `%s`를 빠뜨리면 런타임에서야 터지기 때문이다.
        """
        if params is not None and query.count("%s") != len(params):
            raise AssertionError(
                f"자리표시자 {query.count('%s')}개와 파라미터 {len(params)}개가 다릅니다."
            )
        self.executed.append((query, params))
        rows = self._responses.pop(0) if self._responses else []
        return _FakeCursor(rows)

    @asynccontextmanager
    async def transaction(self):  # type: ignore[no-untyped-def]
        """아무 작업 없이 열린 Transaction 문맥을 제공한다."""
        yield self


def _connection_with_context() -> _FakeConnection:
    """Context 조회, INT-013 매칭(없음), Job·생성 요청 INSERT 순서의 응답을 준비한다."""
    return _FakeConnection(
        [
            [{"id": "context-1", "plan": "free", "preferred_language": "ko"}],
            [],  # SINGLE_TOPIC 접수 시 INT-013 매칭 조회 — 활성 관심사와 일치 없음
            [{"id": "job-1"}],
            [{"id": "request-1"}],
        ]
    )


def test_upsert_user_context_persists_onboarding_selections() -> None:
    """온보딩 Category·Topic과 taxonomy version이 Snapshot과 checksum 입력에 포함된다."""
    created_at = datetime(2026, 8, 4, tzinfo=UTC)
    connection = _FakeConnection(
        [
            [],
            [],
            [{"id": "context-1", "created_at": created_at}],
        ]
    )

    stored = asyncio.run(
        upsert_user_context_snapshot(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            context_version=2,
            plan="free",
            preferred_language="ko",
            personalization_enabled=True,
            interest_taxonomy_version="1.0.0",
            selected_category_ids=["tech", "business"],
            selected_topic_ids=["ai_ml", "startup"],
            blocked_interest_ids=[],
            blocked_source_ids=[],
        )
    )

    insert_sql, insert_params = connection.executed[2]
    assert "interest_taxonomy_version" in insert_sql
    assert "selected_category_ids" in insert_sql
    assert "selected_topic_ids" in insert_sql
    assert insert_params is not None
    assert insert_params[5:8] == (
        "1.0.0",
        ["tech", "business"],
        ["ai_ml", "startup"],
    )
    assert len(str(insert_params[-1])) == 64
    assert stored.selected_category_ids == ["tech", "business"]
    assert stored.selected_topic_ids == ["ai_ml", "startup"]


def test_enqueue_persists_scheduled_at_for_reserved_generation() -> None:
    """예약 시각을 지정하면 Job INSERT에 scheduled_at 값이 전달된다."""
    connection = _connection_with_context()
    scheduled = datetime(2026, 7, 21, 7, 0, tzinfo=UTC)

    submission = asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="2026-07-21-user-1-interest_news_card",
            topic="개인 지식 그래프",
            content_type="interest_news_card",
            language="ko",
            scheduled_at=scheduled,
            request_id="request-1",
        )
    )

    assert submission.job_id == "job-1"
    assert submission.generation_request_id == "request-1"
    insert_sql, insert_params = connection.executed[2]
    assert "scheduled_at" in insert_sql
    assert "COALESCE(%s, clock_timestamp())" in insert_sql
    assert insert_params is not None and insert_params[-1] == scheduled


def test_enqueue_defaults_to_immediate_execution_without_schedule() -> None:
    """예약 시각을 생략하면 scheduled_at 파라미터가 NULL로 전달된다."""
    connection = _connection_with_context()

    asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-immediate",
            topic="개인 지식 그래프",
            content_type="interest_news_card",
            language=None,
            request_id="request-1",
        )
    )

    _, insert_params = connection.executed[2]
    assert insert_params is not None and insert_params[-1] is None


def test_enqueue_carries_change_history_toggle_in_the_job_payload() -> None:
    """변경점 추적 토글은 Job Payload(jsonb)에 실려 실행 시점까지 전달된다.

    서버가 사용자별 켬/끔 상태를 들고 있지 않으므로 컬럼·테이블 변경 없이
    요청마다 따라오는 값으로 처리한다.
    """
    connection = _connection_with_context()

    asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-delta",
            topic="반도체",
            content_type="interest_news_card",
            language="ko",
            change_history_enabled=True,
            request_id="request-1",
        )
    )

    _, insert_params = connection.executed[2]
    assert insert_params is not None
    payload = insert_params[2].obj
    assert payload["change_history_enabled"] is True


def test_enqueue_defaults_change_history_toggle_to_off() -> None:
    """토글을 지정하지 않으면 꺼진 상태로 등록된다(기존 동작 유지)."""
    connection = _connection_with_context()

    asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-plain",
            topic="반도체",
            content_type="interest_news_card",
            language="ko",
            request_id="request-1",
        )
    )

    _, insert_params = connection.executed[2]
    assert insert_params is not None
    assert insert_params[2].obj["change_history_enabled"] is False


def test_enqueue_wiki_briefing_does_not_read_registered_interests() -> None:
    """Wiki 브리핑 접수는 사용자 관심사 매칭 없이 준비 날짜만 Job에 고정한다."""
    connection = _FakeConnection(
        [
            [{"id": "context-1", "plan": "free", "preferred_language": "ko"}],
            [{"id": "job-1"}],
            [{"id": "request-1"}],
        ]
    )

    asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-wiki-briefing",
            topic="오늘의 관심사 브리핑",
            generation_scope="WIKI_BRIEFING",
            content_type="interest_news_card",
            briefing_date=date(2026, 8, 12),
            language="ko",
            request_id="request-1",
        )
    )

    assert len(connection.executed) == 3
    assert all("user_interests" not in query for query, _ in connection.executed)
    _, job_params = connection.executed[1]
    assert job_params is not None
    payload = job_params[2].obj
    assert payload["generation_scope"] == "WIKI_BRIEFING"
    assert payload["topics"] == []
    assert payload["briefing_date"] == "2026-08-12"


def test_enqueue_pins_read_pipeline_version_in_job_payload() -> None:
    """Report Job은 접수 시점의 읽기 루프 버전을 Payload에 고정한다."""
    connection = _connection_with_context()

    asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-v2-reader",
            topic="반도체",
            content_type="interest_news_card",
            language="ko",
            request_id="request-1",
            read_pipeline_version="langgraph_v2",
        )
    )

    _, insert_params = connection.executed[2]
    assert insert_params is not None
    assert insert_params[2].obj["read_pipeline_version"] == "langgraph_v2"


def test_enqueue_defaults_missing_read_pipeline_version_to_legacy() -> None:
    """전환 설정을 생략한 접수는 V1 호환 버전을 명시적으로 저장한다."""
    connection = _connection_with_context()

    asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-v1-reader",
            topic="반도체",
            content_type="interest_news_card",
            language="ko",
            request_id="request-1",
        )
    )

    _, insert_params = connection.executed[2]
    assert insert_params is not None
    assert insert_params[2].obj["read_pipeline_version"] == "legacy_v1"


def test_enqueue_batch_report_freezes_database_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch 접수는 LLM 호출 전에 Personal Wiki·Global 검색 결과를 Payload에 고정한다."""
    connection = _connection_with_context()
    fixed = ReportContextDocument(
        reference="P1",
        document_version_id="version-1",
        chunk_id="chunk-1",
        namespace_key="user/user-1",
        title="고정 근거",
        content="접수 시점의 개인 Wiki 내용",
        url=None,
        score=0.9,
    )

    async def fake_load(*args: object, **kwargs: object) -> list[ReportContextDocument]:
        """접수 시점의 고정 검색 Context를 반환한다."""
        return [fixed]

    monkeypatch.setattr(generation_runtime, "load_report_context", fake_load)

    asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-batch",
            topic="AI 에이전트",
            content_type="interest_news_card",
            language="ko",
            execution_mode="batch",
            request_id="request-1",
        )
    )

    _, job_params = connection.executed[2]
    assert job_params is not None
    payload = job_params[2].obj
    assert payload["execution_mode"] == "batch"
    assert payload["batch_contexts"][0]["chunk_id"] == "chunk-1"
    assert payload["batch_contexts"][0]["content"] == "접수 시점의 개인 Wiki 내용"


def test_enqueue_captures_active_wiki_build_for_navigation() -> None:
    """Job 접수 시점의 활성 Wiki Build UUID를 Payload에 고정한다."""
    connection = _FakeConnection(
        [
            [
                {
                    "id": "context-1",
                    "plan": "free",
                    "preferred_language": "ko",
                    "wiki_version_id": "wiki-build-9",
                }
            ],
            [],
            [{"id": "job-1"}],
            [{"id": "request-1"}],
        ]
    )

    asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-wiki-snapshot",
            topic="삼성전자",
            content_type="interest_news_card",
            language="ko",
            request_id="request-1",
        )
    )

    context_sql, _ = connection.executed[0]
    _, job_params = connection.executed[2]
    assert "FROM agent.wiki_versions AS wiki" in context_sql
    assert job_params is not None
    assert job_params[2].obj["wiki_version_id"] == "wiki-build-9"


def test_enqueue_pins_on_demand_navigation_profile_and_budget() -> None:
    """온디맨드 2-hop 이름과 실제 예산을 Job Payload에 함께 고정한다."""
    connection = _connection_with_context()

    asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-on-demand-2hop",
            topic="AI 에이전트",
            navigation_profile="ON_DEMAND_2HOP",
            content_type="interest_news_card",
            language="ko",
            request_id="request-1",
        )
    )

    _, job_params = connection.executed[2]
    assert job_params is not None
    payload = job_params[2].obj
    assert payload["navigation_profile"] == "ON_DEMAND_2HOP"
    assert payload["navigation_budget"] == {
        "max_depth": 2,
        "max_seed_pages": 2,
        "max_pages": 6,
        "max_chunks": 12,
        "hop_page_limits": [2, 2],
    }


def test_navigation_snapshot_persists_selected_versions_and_saved_at() -> None:
    """첫 Reader Packet의 Page·Source 시각을 Topic별 Job Payload에 저장한다."""
    now = datetime(2026, 8, 10, 9, 30, tzinfo=UTC)
    packet = WikiNavigationPacket(
        query="최근 삼성전자 관심",
        wiki_version_id="wiki-build-9",
        candidates=(),
        pages=(
            WikiNavigationPage(
                document_id="doc-samsung",
                document_version_id="version-samsung",
                document_kind="entity",
                document_key="삼성전자",
                file_path="entities/삼성전자.md",
                title="삼성전자",
                aliases=(),
                summary="반도체 기업",
                markdown="# 삼성전자",
                version=2,
                updated_at=now,
                role="seed",
            ),
        ),
        relations=(),
        sources=(
            WikiNavigationSource(
                wiki_document_version_id="version-samsung",
                source_document_id="source-1",
                source_document_version_id="source-version-1",
                source_type="web_clipping",
                title="삼성전자 저장 글",
                url="https://example.com/samsung",
                relation_type="derived_from",
                saved_at=now,
                saved_at_source="event_occurred_at",
                stored_at=now,
                published_at=None,
                clipped_on=None,
            ),
        ),
        trace=(),
    )
    connection = _FakeConnection([[], [{"id": "job-1"}]])

    asyncio.run(
        persist_report_navigation_snapshot(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            topic="삼성전자",
            packets=[packet],
        )
    )

    sql, params = connection.executed[1]
    assert "wiki_navigation_snapshots" in sql
    assert "jsonb_build_object(%s::text, %s::jsonb)" in sql
    assert params is not None and params[0] == "삼성전자"
    snapshot = params[1].obj
    assert snapshot["selected_document_version_ids"] == ["version-samsung"]
    assert snapshot["sources"][0]["saved_at"] == now.isoformat()
    assert snapshot["budget"] == {
        "max_depth": 1,
        "max_seed_pages": 6,
        "max_pages": 6,
        "max_chunks": 12,
        "hop_page_limits": [6],
    }
    assert snapshot["pages"][0]["hops"] == 0
    assert snapshot["hop_page_counts"] == {"0": 1}


def test_enqueue_stores_report_type_for_the_publish_snapshot() -> None:
    """요청의 report_type을 Job payload와 요청 parameters에 함께 남긴다.

    Agent는 이 값을 해석하지 않는다. 발행 시점에 그대로 꺼내 돌려주려면
    요청 행에 남아 있어야 해서 parameters jsonb에 보관한다.
    """
    connection = _connection_with_context()

    asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-morning",
            topic="개인 지식 그래프",
            content_type="interest_news_card",
            report_type="MORNING_BRIEFING",
            language="ko",
            request_id="request-1",
        )
    )

    _, job_params = connection.executed[2]
    assert job_params is not None
    assert job_params[2].obj["report_type"] == "MORNING_BRIEFING"
    _, request_params = connection.executed[3]
    assert request_params is not None
    assert request_params[-1].obj["report_type"] == "MORNING_BRIEFING"


def test_enqueue_pins_explicit_briefing_date_without_interpreting_report_type() -> None:
    """Service가 명시한 브리핑 날짜만 Job에 고정하고 report_type은 해석하지 않는다."""
    connection = _FakeConnection(
        [
            [{"id": "context-1", "plan": "free", "preferred_language": "ko"}],
            [],  # 대표 topic INT-013
            [],  # 반도체 INT-013
            [],  # 프로야구 INT-013
            [{"id": "job-1"}],
            [{"id": "request-1"}],
        ]
    )

    asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-prewarmed-morning",
            topic="오늘의 관심사 브리핑",
            topics=["반도체", "프로야구"],
            content_type="interest_news_card",
            report_type="CUSTOM_SERVICE_VALUE",
            briefing_date=date(2026, 8, 12),
            language="ko",
            request_id="request-1",
        )
    )

    _, job_params = connection.executed[4]
    assert job_params is not None
    assert job_params[2].obj["briefing_date"] == "2026-08-12"
    assert job_params[2].obj["report_type"] == "CUSTOM_SERVICE_VALUE"
    _, request_params = connection.executed[5]
    assert request_params is not None
    assert request_params[-1].obj["briefing_date"] == "2026-08-12"


def test_enqueue_snapshots_active_interest_bundle() -> None:
    """활성 관심사와 1홉 Wiki 노드를 접수 시점 Job·요청 Payload에 고정한다."""
    connection = _FakeConnection(
        [
            [{"id": "context-1", "plan": "free", "preferred_language": "ko"}],
            [],
            [
                {
                    "profile_id": "profile-1",
                    "profile_version": 7,
                    "topic": "생성형 AI",
                    "score": 0.91,
                    "document_ids": ["11111111-1111-4111-8111-111111111111"],
                }
            ],
            [
                {
                    "document_id": "11111111-1111-4111-8111-111111111111",
                    "document_version_id": "44444444-4444-4444-8444-444444444444",
                    "keyword": "생성형 AI",
                    "document_kind": "concept",
                    "summary": "생성 모델 기반 인공지능",
                    "aliases": ["Generative AI"],
                    "updated_at": "2026-08-09T10:00:00+00:00",
                }
            ],
            [
                {
                    "document_id": "22222222-2222-4222-8222-222222222222",
                    "document_version_id": "55555555-5555-4555-8555-555555555555",
                    "keyword": "AI 에이전트",
                    "document_kind": "concept",
                    "summary": "도구를 사용해 목표를 수행하는 AI",
                    "aliases": ["Agentic AI"],
                    "updated_at": "2026-08-08T10:00:00+00:00",
                    "weight": 1.0,
                    "relation_types": ["applies_concept"],
                    "relations": [
                        {
                            "relation_id": "88888888-8888-4888-8888-888888888888",
                            "root_document_id": "11111111-1111-4111-8111-111111111111",
                            "direction": "root_to_neighbor",
                            "relation_type": "applies_concept",
                            "confidence": 0.96,
                            "provenance_kind": "source_explicit",
                            "review_status": "accepted",
                            "rationale": "에이전트는 생성형 AI를 적용한다.",
                            "supports": [
                                {
                                    "source_document_version_id": (
                                        "99999999-9999-4999-8999-999999999999"
                                    ),
                                    "provenance_kind": "source_explicit",
                                    "confidence": 0.96,
                                    "review_status": "accepted",
                                    "evidence": "생성형 AI 기반 에이전트",
                                    "rationale": "원문 명시",
                                }
                            ],
                        }
                    ],
                    "shared_source_count": 2,
                    "degree": 3.0,
                }
            ],
            [{"id": "job-1"}],
            [{"id": "request-1"}],
        ]
    )

    submission = asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-bundle",
            topic=None,
            generation_scope="INTEREST_BUNDLE",
            interest_id="33333333-3333-4333-8333-333333333333",
            content_type="interest_news_card",
            language="ko",
            request_id="request-1",
        )
    )

    assert submission.job_id == "job-1"
    _, job_params = connection.executed[5]
    assert job_params is not None
    payload = job_params[2].obj
    assert payload["topic"] == "생성형 AI"
    assert payload["topics"] == []
    assert payload["generation_scope"] == "INTEREST_BUNDLE"
    assert payload["interest_bundle"]["profile_version"] == 7
    assert payload["interest_bundle"]["keywords"] == ["생성형 AI", "AI 에이전트"]
    assert (
        payload["interest_bundle"]["root"]["documents"][0][
            "document_version_id"
        ]
        == "44444444-4444-4444-8444-444444444444"
    )
    assert (
        payload["interest_bundle"]["neighbors"][0]["document_version_id"]
        == "55555555-5555-4555-8555-555555555555"
    )
    assert (
        payload["interest_bundle"]["neighbors"][0]["relations"][0]["direction"]
        == "root_to_neighbor"
    )
    assert (
        payload["interest_bundle"]["neighbors"][0]["relations"][0]["supports"][
            0
        ]["evidence"]
        == "생성형 AI 기반 에이전트"
    )
    _, request_params = connection.executed[6]
    assert request_params is not None
    assert request_params[3] == "생성형 AI"
    assert request_params[-1].obj["interest_bundle"] == payload["interest_bundle"]


def test_enqueue_single_topic_snapshots_bundle_when_topic_matches_active_interest() -> None:
    """SINGLE_TOPIC 주제가 활성 관심사와 일치하면 INT-012 묶음을 함께 고정한다.

    interest-bundle-report-design.md §9 — 반응형 1홉 검색 대신 접수 시 고정
    스냅샷을 쓰게 하는 판정 지점(INT-013)의 결과가 Job Payload에 실려야 한다.
    """
    connection = _FakeConnection(
        [
            [{"id": "context-1", "plan": "free", "preferred_language": "ko"}],
            [{"interest_id": "33333333-3333-4333-8333-333333333333"}],
            [
                {
                    "profile_id": "profile-1",
                    "profile_version": 7,
                    "topic": "코스피",
                    "score": 0.91,
                    "document_ids": [],
                }
            ],
            [{"id": "job-1"}],
            [{"id": "request-1"}],
        ]
    )

    submission = asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-single-topic-matched",
            topic="코스피",
            content_type="interest_news_card",
            language="ko",
            request_id="request-1",
        )
    )

    assert submission.job_id == "job-1"
    _, job_params = connection.executed[3]
    assert job_params is not None
    payload = job_params[2].obj
    assert payload["generation_scope"] == "SINGLE_TOPIC"
    assert payload["topic_interest_bundles"]["코스피"]["interest_id"] == (
        "33333333-3333-4333-8333-333333333333"
    )
    assert payload["topic_interest_bundles"]["코스피"]["keywords"] == ["코스피"]


def test_enqueue_single_topic_leaves_bundle_empty_without_a_match() -> None:
    """일치하는 활성 관심사가 없으면 topic_interest_bundles가 비어 있다."""
    connection = _connection_with_context()

    asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-single-topic-unmatched",
            topic="환율",
            content_type="interest_news_card",
            language="ko",
            request_id="request-1",
        )
    )

    _, job_params = connection.executed[2]
    assert job_params is not None
    assert job_params[2].obj["topic_interest_bundles"] == {}


def test_load_pinned_wiki_context_uses_exact_snapshot_versions() -> None:
    """Worker는 현재 Version 재검색 없이 Job에 고정된 Version을 루트 우선 조회한다."""
    connection = _FakeConnection(
        [
            [],
            [
                {
                    "document_version_id": "44444444-4444-4444-8444-444444444444",
                    "title": "생성형 AI",
                    "summary": "생성 모델 기반 인공지능",
                    "chunk_id": "66666666-6666-4666-8666-666666666666",
                    "content": "## Description\n사용자의 기존 관심 맥락",
                },
                {
                    "document_version_id": "55555555-5555-4555-8555-555555555555",
                    "title": "AI 에이전트",
                    "summary": "목표를 수행하는 AI",
                    "chunk_id": "77777777-7777-4777-8777-777777777777",
                    "content": "## Definition\n도구 사용과 계획 실행",
                },
            ],
        ]
    )
    bundle = {
        "root": {
            "documents": [
                {
                    "document_version_id": "44444444-4444-4444-8444-444444444444",
                    "keyword": "생성형 AI",
                    "updated_at": "2026-08-09T10:00:00+00:00",
                }
            ]
        },
        "neighbors": [
            {
                "document_version_id": "55555555-5555-4555-8555-555555555555",
                "keyword": "AI 에이전트",
                "updated_at": "2026-08-08T10:00:00+00:00",
            }
        ],
    }

    contexts = asyncio.run(
        load_pinned_wiki_context(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            interest_bundle=bundle,
        )
    )

    query, params = connection.executed[1]
    assert "unnest(%s::uuid[]) WITH ORDINALITY" in query
    assert "version.id = requested.version_id" in query
    assert "document.current_version" not in query
    assert params == (
        [
            "44444444-4444-4444-8444-444444444444",
            "55555555-5555-4555-8555-555555555555",
        ],
        "user/user-1",
    )
    assert [context.context_role for context in contexts] == [
        "wiki_root",
        "wiki_neighbor",
    ]
    assert [context.reference for context in contexts] == ["P1", "P2"]
    assert contexts[0].source_updated_at == "2026-08-09T10:00:00+00:00"
    assert "사용자의 기존 관심 맥락" in contexts[0].content


def test_load_personal_wiki_vector_context_uses_active_matching_model() -> None:
    """Vector 검색은 현재 Wiki와 active 동일 모델 Embedding만 Cosine top-k 조회한다."""
    connection = _FakeConnection(
        [
            [
                {
                    "document_version_id": "44444444-4444-4444-8444-444444444444",
                    "chunk_id": "66666666-6666-4666-8666-666666666666",
                    "namespace_key": "user/user-1",
                    "title": "폭염",
                    "content": "장기간 높은 기온이 이어지는 현상",
                    "url": None,
                    "updated_at": "2026-08-09T10:00:00+00:00",
                    "score": 0.82,
                }
            ]
        ]
    )

    contexts = asyncio.run(
        load_personal_wiki_vector_context(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            query_embedding=[0.1] * 1536,
            model_name="text-embedding-3-small",
            top_k=5,
        )
    )

    query, params = connection.executed[0]
    assert "wiki_embedding.embedding <=> query_vector.embedding" in query
    assert "config.status = 'active'" in query
    assert "document.current_version = version.version" in query
    assert "document.document_kind IN ('entity', 'concept')" in query
    assert "GREATEST(0.0, 1.0 - distance) + 0.05" in query
    assert params is not None
    assert str(params[0]).startswith("[0.1,0.1")
    assert params[1:] == (
        "personal-wiki/text-embedding-3-small",
        "text-embedding-3-small",
        "user/user-1",
        "text-embedding-3-small",
        5,
    )
    assert contexts[0].context_role == "semantic_retrieval"
    assert contexts[0].source_updated_at == "2026-08-09T10:00:00+00:00"


def test_load_personal_wiki_vector_context_rejects_wrong_dimensions() -> None:
    """DB 호출 전 Query Embedding 차원을 검증한다."""
    connection = _FakeConnection([])

    with pytest.raises(ValueError, match="1536차원"):
        asyncio.run(
            load_personal_wiki_vector_context(
                connection,  # type: ignore[arg-type]
                user_id="user-1",
                query_embedding=[0.1, 0.2],
                model_name="text-embedding-3-small",
            )
        )

    assert connection.executed == []


def test_enqueue_bundle_retry_returns_snapshot_without_revalidating_interest() -> None:
    """멱등 재시도는 Profile이 바뀌어도 최초 Job과 묶음 스냅샷을 그대로 재사용한다."""
    connection = _FakeConnection(
        [
            [{"id": "context-1", "plan": "free", "preferred_language": "ko"}],
            [{"id": "job-1", "generation_request_id": "request-1"}],
        ]
    )

    submission = asyncio.run(
        enqueue_report_generation_job(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            idempotency_key="generation-bundle",
            topic=None,
            generation_scope="INTEREST_BUNDLE",
            interest_id="33333333-3333-4333-8333-333333333333",
            content_type="interest_news_card",
            language="ko",
            request_id="request-retry",
        )
    )

    assert submission.job_id == "job-1"
    assert submission.generation_request_id == "request-1"
    assert len(connection.executed) == 2
    assert "user_interests" not in connection.executed[1][0]


def test_uuid_or_none_keeps_wiki_ids_and_drops_live_references() -> None:
    """Wiki UUID는 유지하고 실시간 자료 참조(L1 등)·빈 값은 None으로 바꾼다.

    citations의 document_version_id·chunk_id는 uuid 컬럼 + Wiki FK라서,
    UUID가 아닌 값을 그대로 넣으면 실시간 근거 인용 저장이 실패한다.
    """
    from infrastructure.persistence.features.generation_runtime import _uuid_or_none

    wiki_id = "0d4f6f5e-2f3a-4b9c-8a1d-3e5f7a9b1c2d"
    assert _uuid_or_none(wiki_id) == wiki_id
    assert _uuid_or_none("L1") is None
    assert _uuid_or_none("") is None


def _connection_for_persist(
    topic: str,
    parameters: dict[str, Any] | None = None,
    request_idempotency_key: str | None = None,
    *,
    job_payload: dict[str, Any] | None = None,
    cited_taxonomy_rows: list[dict[str, Any]] | None = None,
    catalog: list[dict[str, Any]] | None = None,
    citation_count: int = 0,
) -> _FakeConnection:
    """인용 없는 리포트 저장 경로가 실행할 질의 순서대로 응답을 준비한다.

    request_idempotency_key를 주지 않으면 Job 조인 컬럼이 없는 행이 되어,
    이 컬럼을 읽기 전에 저장된 데이터를 만나는 상황을 재현한다.

    taxonomy 파생은 인용 원본 조회(①)가 비었을 때만 이름 조회(②)를 실행하므로,
    ①에 값을 주면 ② 응답은 목록에 넣지 않는다 — 넣으면 뒤 질의와 한 칸씩 어긋난다.
    """
    request_row: dict[str, Any] = {"id": "request-1", "topic": topic}
    if parameters is not None:
        request_row["parameters"] = parameters
    if request_idempotency_key is not None:
        request_row["request_idempotency_key"] = request_idempotency_key
    if job_payload is not None:
        request_row["job_payload"] = job_payload
    cited = cited_taxonomy_rows or []
    responses: list[list[dict[str, Any]]] = [
        [request_row],  # generation_requests 조회
        [],  # status = running
        [{"id": "run-1"}],  # generation_runs INSERT
        [{"next_version": 1}],  # 다음 content 버전
        [],  # 이전 후보 superseded
        [{"id": "cand-1", "created_at": datetime(2026, 7, 30, tzinfo=UTC)}],
        *[[{"id": f"citation-{index}"}] for index in range(citation_count)],
        [],  # generation_runs completed
        [],  # generation_requests completed
        cited,  # taxonomy 파생 ① 인용 원본
    ]
    if not cited:
        # taxonomy 파생 ② — 카탈로그를 통째로 읽어 파이썬에서 맞춘다.
        responses.append(
            _DEFAULT_TAXONOMY_CATALOG if catalog is None else catalog
        )
    responses.extend(
        [
            [],  # publish_snapshots INSERT
            [],  # event_outbox INSERT
        ]
    )
    return _FakeConnection(responses)


def _taxonomy_row(topic_id: str, version: str = "1.0.0-draft", *,
                  first_ordinal: int = 0, hits: int = 1) -> dict[str, Any]:
    """taxonomy 파생 ①(인용 원본) 질의가 돌려주는 행 하나를 만든다."""
    return {
        "taxonomy_version": version,
        "topic_id": topic_id,
        "first_ordinal": first_ordinal,
        "hits": hits,
    }


def _catalog_row(topic_id: str, name: str, keywords: list[str] | None = None,
                 version: str = "1.0.0-draft") -> dict[str, Any]:
    """taxonomy 카탈로그 한 행 — 파생 ②가 이걸 통째로 읽어 맞춘다."""
    return {
        "taxonomy_version": version,
        "topic_id": topic_id,
        "name": name,
        "keywords": keywords or [],
    }


# 실제 V11 카탈로그에서 이 테스트가 쓰는 만큼만 옮긴 것 — 이름·keywords 모양을 그대로 지킨다.
_DEFAULT_TAXONOMY_CATALOG = [
    _catalog_row("ai_ml", "AI·머신러닝",
                 ["생성형 AI", "LLM", "머신러닝", "AI 에이전트", "OpenAI", "Anthropic"]),
    _catalog_row("economy", "경제·금융",
                 ["금리", "환율", "물가", "경기 전망", "중앙은행", "인플레이션"]),
    _catalog_row("industry", "산업·기업",
                 ["실적 발표", "빅테크", "반도체", "인수합병", "산업 동향", "공급망"]),
    _catalog_row("realestate", "부동산", ["부동산", "집값", "청약"]),
]


def _executed_sql_containing(connection: _FakeConnection, needle: str):
    """기록된 질의 중 needle을 포함한 첫 번째 (sql, params)를 돌려준다."""
    for sql, params in connection.executed:
        if needle in sql:
            return sql, params
    return None, None


def _publish_payload(connection: _FakeConnection) -> dict[str, Any]:
    """기록된 질의에서 publish_snapshots INSERT의 payload를 꺼낸다."""
    for sql, params in connection.executed:
        if "INSERT INTO agent.publish_snapshots" in sql:
            assert params is not None
            return params[5].obj  # Jsonb로 감싼 payload
    raise AssertionError("publish_snapshots INSERT를 찾지 못했다.")


def _persist(
    connection: _FakeConnection, *, change_history_used: bool = False
) -> None:
    """인용 없는 최소 리포트 한 건을 저장 경로에 통과시킨다."""
    asyncio.run(
        persist_report_generation(
            connection,  # type: ignore[arg-type]
            job_id="job-1",
            user_id="user-1",
            attempt_number=1,
            content_type="interest_news_card",
            generated=GeneratedReportContent(
                title="제목",
                summary="요약",
                body="본문",
                citation_references=(),
            ),
            contexts=[],
            latency_ms=100,
            change_history_used=change_history_used,
        )
    )


def test_publish_payload_carries_request_topic_as_interest_tag() -> None:
    """발행 Snapshot payload에 생성 요청 topic이 카드 태그로 실린다.

    service 워커가 이 값을 card_interest_tags에 그대로 저장하므로,
    빠지면 카드에 관심사 태그가 붙지 않는다.
    """
    connection = _connection_for_persist("코스피")

    _persist(connection)

    assert _publish_payload(connection)["tags"] == ["코스피"]


def test_publish_payload_carries_cover_image_from_used_citation() -> None:
    """실제로 인용한 외부 출처의 이미지만 발행 Snapshot 상단 이미지가 된다."""
    connection = _connection_for_persist("코스피", citation_count=1)
    context = ReportContextDocument(
        reference="G1",
        document_version_id="gsrc:00000000-0000-0000-0000-000000000001",
        chunk_id="gsrc:00000000-0000-0000-0000-000000000001",
        namespace_key="global",
        title="코스피 기사",
        content="코스피가 상승했다.",
        url="https://news.example/kospi",
        score=1.0,
        image_url="https://cdn.example/kospi.jpg",
    )

    asyncio.run(
        persist_report_generation(
            connection,  # type: ignore[arg-type]
            job_id="job-1",
            user_id="user-1",
            attempt_number=1,
            content_type="interest_news_card",
            generated=GeneratedReportContent(
                title="제목",
                summary="요약",
                body="코스피 동향이다 [G1]",
                citation_references=("G1",),
            ),
            contexts=[context],
            latency_ms=100,
        )
    )

    assert _publish_payload(connection)["cover_image"] == {
        "url": "https://cdn.example/kospi.jpg",
        "source_url": "https://news.example/kospi",
        "source_title": "코스피 기사",
        "reference": "G1",
    }


def test_context_image_replaces_global_cached_banner_from_markdown() -> None:
    """Global 조회 Context는 배너 캐시 대신 본문 속 기사 이미지를 사용한다."""
    row = {
        "namespace_key": "global",
        "title": "본문 대표 이미지를 다시 찾는 긴 기사 제목",
        "content": (
            "![광고](https://menu.example/news/banner/ad.jpg)\n"
            "# 본문 대표 이미지를 다시 찾는 긴 기사 제목\n"
            "![사진](https://cdn.example/article/hero.jpg)\n본문"
        ),
        "image_url": "https://menu.example/news/banner/ad.jpg",
    }

    assert generation_runtime._context_image_url(row) == (
        "https://cdn.example/article/hero.jpg"
    )


def test_context_image_rejects_ui_asset_outside_global_cache() -> None:
    """개인 Context에 남은 아이콘 URL도 대표 이미지 후보에서 제외한다."""
    row = {
        "namespace_key": "user/1",
        "title": "개인 문서",
        "content": "본문",
        "image_url": "https://wiki.example/images/ico_search.png",
    }

    assert generation_runtime._context_image_url(row) is None


def test_publish_payload_derives_taxonomy_topics_from_cited_sources() -> None:
    """인용한 Global 수집 문서의 수집 대상에서 taxonomy Topic을 파생한다(①).

    Service가 이 식별자로 뷰어 관심사와 카드의 교집합을 계산한다. 카드에는
    자유 문자열 태그밖에 없어서 그 계산이 불가능했던 자리를 메우는 값이다.
    """
    connection = _connection_for_persist(
        "반도체",
        cited_taxonomy_rows=[
            _taxonomy_row("industry", first_ordinal=0, hits=2),
            _taxonomy_row("ai_ml", first_ordinal=1, hits=1),
        ],
    )

    _persist(connection)

    payload = _publish_payload(connection)
    assert payload["taxonomy_topic_ids"] == ["industry", "ai_ml"]
    assert payload["taxonomy_version"] == "1.0.0-draft"


def test_publish_payload_skips_name_lookup_when_citations_already_matched() -> None:
    """①이 값을 내면 ②(이름 조회)는 아예 실행하지 않는다.

    근거 기반 파생이 이름 매칭보다 정확하므로 덮어쓰거나 합치지 않는다.
    """
    connection = _connection_for_persist(
        "반도체", cited_taxonomy_rows=[_taxonomy_row("industry")]
    )

    _persist(connection)

    sql, _ = _executed_sql_containing(connection, "agent.interest_taxonomy_topics")
    assert sql is None


def test_publish_payload_falls_back_to_requested_topic_name() -> None:
    """인용 원본이 없으면 요청 주제 이름으로 taxonomy를 찾는다(②).

    개인 Wiki만 인용한 리포트가 여기 해당한다 — 개인 Wiki 청크에는 수집 대상이 없다.
    """
    connection = _connection_for_persist("AI·머신러닝")

    _persist(connection)

    assert _publish_payload(connection)["taxonomy_topic_ids"] == ["ai_ml"]


def test_publish_payload_matches_requested_topic_by_keyword() -> None:
    """정식 이름이 아닌 keywords 항목으로도 찾는다.

    2026-08-11 리허설: 요청 `반도체`가 0건이었다. 이름이 아니라 `industry`의
    keywords 항목이기 때문이다. 큐레이팅된 목록과의 완전 일치라 fuzzy가 아니다.
    """
    connection = _connection_for_persist("반도체")

    _persist(connection)

    assert _publish_payload(connection)["taxonomy_topic_ids"] == ["industry"]


def test_publish_payload_matches_requested_topic_by_name_token() -> None:
    """정식 이름을 구분자로 쪼갠 조각으로도 찾는다 — 대소문자는 무시한다.

    2026-08-11 리허설: `AI`·`경제`가 0건이었다. 각각 `AI·머신러닝`·`경제·금융`의
    앞 조각이라 이름 완전 일치로는 안 걸린다.
    """
    connection = _connection_for_persist(
        "오늘의 관심사 브리핑", job_payload={"topics": ["ai", "경제"]}
    )

    _persist(connection)

    assert _publish_payload(connection)["taxonomy_topic_ids"] == ["ai_ml", "economy"]


def test_publish_payload_skips_ambiguous_name_token() -> None:
    """한 조각이 여러 Topic에 걸리면 그 조각은 버린다(2026-08-11 우석 안전핀).

    모호할 때 안 붙이는 쪽이 엉뚱하게 붙는 것보다 낫다 — 규칙을 결정적으로 유지한다.
    """
    connection = _connection_for_persist(
        "금융",
        catalog=[
            _catalog_row("economy", "경제·금융"),
            _catalog_row("invest", "투자·금융"),   # `금융`이 두 Topic에 걸린다
        ],
    )

    _persist(connection)

    assert _publish_payload(connection)["taxonomy_topic_ids"] == []


def test_publish_payload_prefers_full_name_over_token() -> None:
    """정식 이름이 맞으면 조각 매칭으로 내려가지 않는다.

    `부동산`은 그 자체가 정식 이름이므로, 다른 이름의 조각과 겹쳐도 이름이 이긴다.
    """
    connection = _connection_for_persist(
        "부동산",
        catalog=[
            _catalog_row("realestate", "부동산"),
            _catalog_row("policy", "부동산·정책"),   # 조각으로는 여기에도 걸린다
        ],
    )

    _persist(connection)

    assert _publish_payload(connection)["taxonomy_topic_ids"] == ["realestate"]


def test_publish_payload_uses_job_topics_for_morning_briefing() -> None:
    """아침 브리핑은 요청 topic이 아니라 Job payload의 topics로 찾는다.

    generation_requests.topic은 카드 제목용 **고정 문구**라, 그걸로 taxonomy를
    찾으면 아침 브리핑은 영영 빈 값이 된다. 실제 주제는 topics[]에만 있다.
    """
    connection = _connection_for_persist(
        "오늘의 관심사 브리핑",
        job_payload={"topics": ["AI·머신러닝", "경제·금융"]},
    )

    _persist(connection)

    assert _publish_payload(connection)["taxonomy_topic_ids"] == ["ai_ml", "economy"]


def test_publish_payload_keeps_taxonomy_empty_when_nothing_matches() -> None:
    """아무 것도 못 찾으면 빈 목록·빈 버전이고 발행은 그대로 진행된다.

    검색·추천 보조 정보라, 이것 때문에 발행이 멈추면 안 된다(content_tags와 같은 원칙).
    """
    connection = _connection_for_persist("taxonomy 밖 주제")

    _persist(connection)

    payload = _publish_payload(connection)
    assert payload["taxonomy_topic_ids"] == []
    assert payload["taxonomy_version"] == ""


def test_publish_payload_skips_name_lookup_without_any_requested_topic() -> None:
    """topic도 topics도 없는 요청(깊게 파기)은 이름 조회를 아예 하지 않는다."""
    connection = _connection_for_persist("")

    _persist(connection)

    sql, _ = _executed_sql_containing(connection, "agent.interest_taxonomy_topics")
    assert sql is None


def test_pick_single_taxonomy_version_drops_minority_version() -> None:
    """버전이 섞이면 매칭이 많은 버전만 남긴다.

    두 버전의 topic_id를 한 배열에 담아 보내면 받는 쪽이 어느 카탈로그로 풀어야
    할지 알 수 없다. 버전과 id는 항상 짝이 맞아야 한다.
    """
    from infrastructure.persistence.features.generation_runtime import (
        _pick_single_taxonomy_version,
    )

    version, topic_ids = _pick_single_taxonomy_version(
        [
            _taxonomy_row("industry", "1.0.0-draft", first_ordinal=0, hits=2),
            _taxonomy_row("ai_ml", "2.0.0", first_ordinal=1, hits=1),
        ]
    )

    assert version == "1.0.0-draft"
    assert topic_ids == ["industry"]


def test_pick_single_taxonomy_version_caps_topic_ids() -> None:
    """한 카드가 주장하는 Topic 수를 상한으로 자른다.

    상한이 없으면 인용을 많이 단 리포트가 Topic 열댓 개를 달고 나가서, 관심사
    교집합 매칭이 사실상 "아무 카드나 걸린다"가 된다.
    """
    from infrastructure.persistence.features.generation_runtime import (
        _MAX_TAXONOMY_TOPIC_IDS,
        _pick_single_taxonomy_version,
    )

    rows = [
        _taxonomy_row(f"topic_{index}", first_ordinal=index)
        for index in range(_MAX_TAXONOMY_TOPIC_IDS + 3)
    ]

    _, topic_ids = _pick_single_taxonomy_version(rows)

    assert len(topic_ids) == _MAX_TAXONOMY_TOPIC_IDS


def test_publish_payload_omits_blank_topic_tag() -> None:
    """공백뿐인 topic은 빈 태그로 노출되지 않도록 제외한다."""
    connection = _connection_for_persist("   ")

    _persist(connection)

    assert _publish_payload(connection)["tags"] == []


def test_publish_payload_returns_the_requested_report_type_unchanged() -> None:
    """요청에서 받은 report_type을 해석 없이 발행 Snapshot에 그대로 싣는다.

    Service는 요청 시점과 Claim 시점이 떨어져 있어, 이 값이 빠지면 카드가 어떤
    맥락에서 만들어졌는지 다시 짜맞춰야 한다(2026-08-06 이송우 협의).
    """
    connection = _connection_for_persist("코스피", {"report_type": "ON_DEMAND"})

    _persist(connection)

    assert _publish_payload(connection)["report_type"] == "ON_DEMAND"


def test_publish_payload_keeps_report_type_empty_for_older_requests() -> None:
    """report_type이 없던 시절 요청 행도 빈 문자열로 안전하게 읽힌다."""
    connection = _connection_for_persist("코스피")

    _persist(connection)

    assert _publish_payload(connection)["report_type"] == ""


def test_publish_payload_reflects_that_the_delta_path_actually_ran() -> None:
    """change_history_enabled는 호출자가 넘긴 실제 실행 결과를 싣는다.

    이 값이 없으면 Service가 body를 "이번에 달라진 점" 4단 구조로 볼지 기존
    자유 형식으로 볼지 헤더 문자열을 파싱해 추측해야 한다.
    """
    connection = _connection_for_persist("코스피")

    _persist(connection, change_history_used=True)

    assert _publish_payload(connection)["change_history_enabled"] is True


def test_publish_payload_ignores_the_requested_toggle_when_the_delta_path_did_not_run() -> None:
    """요청 파라미터가 켜져 있어도, 실제로 델타 경로를 안 탔으면 false로 나간다.

    서버 차단 스위치(CHANGE_HISTORY_ENABLED=0)나 델타 경로 실패로 기존
    generate() 본문이 나갔을 때, 요청 파라미터만 보고 true를 실으면 값과 body
    구조가 어긋난다(2026-08-11 풀스택 피드백). 호출자가 넘긴 실행 결과만
    신뢰해야 한다.
    """
    connection = _connection_for_persist(
        "코스피", {"change_history_enabled": True}
    )

    _persist(connection, change_history_used=False)

    assert _publish_payload(connection)["change_history_enabled"] is False


def test_publish_payload_keeps_change_history_toggle_off_by_default() -> None:
    """호출자가 실행 결과를 안 넘기면 False로 안전하게 처리된다(회귀 0)."""
    connection = _connection_for_persist("코스피")

    _persist(connection)

    assert _publish_payload(connection)["change_history_enabled"] is False


def test_publish_payload_echoes_the_request_idempotency_key() -> None:
    """요청 멱등키를 발행 Snapshot에 원문 그대로 싣는다.

    Service는 이 값으로 대기 중이던 generation_pendings 행과 Claim으로 들어온
    완료 카드를 연결한다. 빠지면 Pending이 완료로 전환되지 않고 cardPublicId도
    실을 수 없다(2026-08-06 협의).
    """
    connection = _connection_for_persist(
        "코스피", request_idempotency_key="2026-08-10-user-1-interest_news_card"
    )

    _persist(connection)

    payload = _publish_payload(connection)
    assert payload["request_idempotency_key"] == "2026-08-10-user-1-interest_news_card"


def test_publish_payload_keeps_request_idempotency_key_empty_when_unknown() -> None:
    """멱등키를 읽지 못한 행도 빈 문자열로 안전하게 저장된다."""
    connection = _connection_for_persist("코스피")

    _persist(connection)

    assert _publish_payload(connection)["request_idempotency_key"] == ""


def test_persist_reads_the_idempotency_key_from_the_job_row() -> None:
    """멱등키는 generation_requests가 아니라 Job 행에서 조인해 읽는다.

    parameters에 복사해 두는 방식이면 이 변경 이전에 등록된 Job이 영영 빈 값으로
    남는다. 조인해서 읽어야 이미 큐에 들어가 있는 Job도 그대로 키가 실린다.
    """
    connection = _connection_for_persist("코스피", request_idempotency_key="key-1")

    _persist(connection)

    request_sql = connection.executed[0][0]
    assert "agent.agent_jobs" in request_sql
    assert "idempotency_key" in request_sql


def test_publish_payload_exposes_interest_bundle_origin() -> None:
    """발행 Snapshot이 범주 리포트의 관심사·Profile·검색 키워드를 추적한다."""
    connection = _connection_for_persist(
        "생성형 AI",
        {
            "generation_scope": "INTEREST_BUNDLE",
            "interest_id": "interest-1",
            "interest_bundle": {
                "profile_id": "profile-1",
                "keywords": ["생성형 AI", "AI 에이전트", "RAG"],
            },
        },
    )

    _persist(connection)

    payload = _publish_payload(connection)
    assert payload["generation_scope"] == "INTEREST_BUNDLE"
    assert payload["source_interest_id"] == "interest-1"
    assert payload["interest_profile_id"] == "profile-1"
    assert payload["bundle_keywords"] == ["생성형 AI", "AI 에이전트", "RAG"]


def test_report_context_search_excludes_wiki_schema_documents() -> None:
    """Wiki 목차(schema) 문서는 본 검색과 폴백 검색 모두에서 제외한다.

    목차 파일은 Namespace의 모든 문서 제목을 담고 있어 어떤 검색어에도 걸리지만
    내용은 링크 목록뿐이라 근거가 되지 못한다. 특히 폴백(매칭 0건일 때 최근
    문서를 채우는 질의)으로 더 자주 들어온다.
    """
    from infrastructure.persistence.features.generation_runtime import (
        load_report_context,
    )

    # 본 검색이 빈 결과 → 폴백 질의까지 실행되게 한다.
    connection = _FakeConnection([[], []])

    asyncio.run(
        load_report_context(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            query="반도체",
        )
    )

    assert len(connection.executed) == 2
    for sql, _ in connection.executed:
        assert "document.document_kind <> 'schema'" in sql
    assert "version.created_at AS source_updated_at" in connection.executed[0][0]
    assert "recency AS source_updated_at" in connection.executed[1][0]


def test_report_context_exposes_version_time_and_retrieval_role() -> None:
    """개인 Wiki Keyword 결과에 정확한 Version 시각과 역할을 전달한다."""
    from infrastructure.persistence.features.generation_runtime import (
        load_report_context,
    )

    updated_at = datetime(2026, 8, 9, 10, 30, tzinfo=UTC)
    connection = _FakeConnection(
        [
            [
                {
                    "document_version_id": "version-1",
                    "chunk_id": "chunk-1",
                    "namespace_key": "user/user-1",
                    "title": "LangGraph",
                    "content": "사용자가 저장한 Wiki 내용",
                    "url": None,
                    "score": 0.8,
                    "source_updated_at": updated_at,
                }
            ]
        ]
    )

    contexts = asyncio.run(
        load_report_context(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            query="LangGraph",
        )
    )

    assert contexts[0].context_role == "keyword_retrieval"
    assert contexts[0].source_updated_at == str(updated_at)


def test_global_report_context_does_not_query_personal_wiki() -> None:
    """Reader의 Global 저장 검색 SQL에는 개인 Wiki Table이 포함되지 않는다."""
    from infrastructure.persistence.features.generation_runtime import (
        load_global_report_context,
    )

    updated_at = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)
    connection = _FakeConnection(
        [
            [
                {
                    "document_version_id": "gsrc:article-1",
                    "chunk_id": "gsrc:article-1",
                    "namespace_key": "global",
                    "title": "삼성전자 반도체 기사",
                    "content": "Global 수집 본문",
                    "url": "https://example.com/article-1",
                    "score": 1.1,
                    "source_updated_at": updated_at,
                }
            ]
        ]
    )

    contexts = asyncio.run(
        load_global_report_context(
            connection,  # type: ignore[arg-type]
            query="삼성전자",
        )
    )

    sql, params = connection.executed[0]
    assert "agent.global_source_documents" in sql
    assert "agent.wiki_chunks" not in sql
    assert "agent.wiki_documents" not in sql
    assert sql.count("%s") == len(params or ())
    assert contexts[0].namespace_key == "global"
    assert contexts[0].context_role == "global_retrieval"


def test_report_context_gives_topic_bonus_through_collection_target() -> None:
    """토픽 가산점을 검색어 글자가 아니라 수집 대상(Topic)으로도 판정한다.

    사용자는 '우주·천문' 같은 라벨을 고르는데 수집은 '스페이스X' 같은 확장
    검색어로 돌린다. 글자만 대조하면 확장 검색어로 모은 자료가 전부 가산점을
    잃어, 주제에 맞는 기사가 잡음과 같은 점수대에 묻힌다.
    """
    from infrastructure.persistence.features.generation_runtime import (
        load_report_context,
    )

    connection = _FakeConnection([[], []])

    asyncio.run(
        load_report_context(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            query="우주·천문",
        )
    )

    main_sql, main_params = connection.executed[0]
    # ① 이 검색어로 직접 수집한 문서
    assert "lower(btrim(mapped.search_query)) = lower(btrim(%s))" in main_sql
    # ② 같은 수집 대상에 묶인 문서 — 라벨과 확장 검색어를 잇는 갈래
    assert "agent.interest_collection_targets AS target" in main_sql
    assert "lower(btrim(target.query)) = lower(btrim(%s))" in main_sql
    # 두 갈래는 OR이어야 한다. AND면 확장 검색어 자료가 오히려 전부 탈락한다.
    assert "OR lower(btrim(target.query))" in main_sql
    # 토픽 판정 갈래가 하나 늘었으므로 검색어 파라미터도 9개에서 10개가 된다.
    # SQL의 %s 개수와 어긋나면 psycopg가 실행 시점에 터지므로 함께 센다.
    assert main_params.count("우주·천문") == 10
    assert main_sql.count("%s") == len(main_params)


def test_publish_payload_separates_generation_topic_from_content_tags() -> None:
    """요청 주제와 콘텐츠 태그를 분리해 싣는다.

    tags는 Service가 card_interest_tags로 소비 중이라 의미를 바꾸지 않는다.
    실제 내용 기반 태그는 content_tags로 따로 전달한다(2026-08-05 이송우 협의).
    """
    connection = _connection_for_persist("의존성 구조")

    asyncio.run(
        persist_report_generation(
            connection,  # type: ignore[arg-type]
            job_id="job-1",
            user_id="user-1",
            attempt_number=1,
            content_type="interest_news_card",
            generated=GeneratedReportContent(
                title="제목",
                summary="요약",
                body="본문",
                citation_references=(),
                content_tags=("강한 결합", "DDD", "Application Layer"),
            ),
            contexts=[],
            latency_ms=100,
        )
    )

    payload = _publish_payload(connection)
    assert payload["generation_topic"] == "의존성 구조"
    assert payload["tags"] == ["의존성 구조"]
    assert payload["content_tags"] == ["강한 결합", "DDD", "Application Layer"]


def test_snapshot_row_mapping_exposes_every_payload_field_we_write() -> None:
    """저장 payload에 넣은 필드가 응답 매핑에서 빠지지 않는지 확인한다.

    읽는 쪽이 키를 명시적으로 고르므로, 쓰는 쪽에만 필드를 추가하면 응답에는
    나오지 않는다(2026-08-05 실측: content_tags가 저장은 됐는데 응답이 늘 빈
    목록이었다).
    """
    from datetime import UTC, datetime

    from infrastructure.persistence.postgres_publish_snapshots import (
        PostgresPublishSnapshotRepository,
    )

    row = {
        "content_id": "content-1",
        "user_id": "user-1",
        "version": 1,
        "snapshot_hash": "h" * 64,
        "created_at": datetime(2026, 8, 5, tzinfo=UTC),
        "payload": {
            "title": "제목",
            "summary": "요약",
            "body": "본문",
            "citations": [],
            "generation_topic": "의존성 구조",
            "tags": ["의존성 구조"],
            "content_tags": ["강한 결합", "DDD"],
            "report_type": "MORNING_BRIEFING",
            "request_idempotency_key": "2026-08-10-user-1-interest_news_card",
            "generation_scope": "INTEREST_BUNDLE",
            "source_interest_id": "interest-1",
            "interest_profile_id": "profile-1",
            "bundle_keywords": ["의존성 구조", "DDD"],
        },
    }

    snapshot = PostgresPublishSnapshotRepository._snapshot_from_row(row)

    assert snapshot.generation_topic == "의존성 구조"
    assert snapshot.tags == ["의존성 구조"]
    assert snapshot.content_tags == ["강한 결합", "DDD"]
    assert snapshot.report_type == "MORNING_BRIEFING"
    assert (
        snapshot.request_idempotency_key == "2026-08-10-user-1-interest_news_card"
    )
    assert snapshot.generation_scope == "INTEREST_BUNDLE"
    assert snapshot.source_interest_id == "interest-1"
    assert snapshot.interest_profile_id == "profile-1"
    assert snapshot.bundle_keywords == ["의존성 구조", "DDD"]


def test_snapshot_row_mapping_tolerates_snapshots_saved_before_new_fields() -> None:
    """새 필드가 없던 시절 Snapshot도 기본값으로 읽힌다."""
    from datetime import UTC, datetime

    from infrastructure.persistence.postgres_publish_snapshots import (
        PostgresPublishSnapshotRepository,
    )

    row = {
        "content_id": "content-1",
        "user_id": "user-1",
        "version": 1,
        "snapshot_hash": "h" * 64,
        "created_at": datetime(2026, 8, 5, tzinfo=UTC),
        "payload": {"title": "제목", "summary": "요약", "body": "본문"},
    }

    snapshot = PostgresPublishSnapshotRepository._snapshot_from_row(row)

    assert snapshot.generation_topic == ""
    assert snapshot.tags == []
    assert snapshot.content_tags == []
    assert snapshot.report_type == ""
    assert snapshot.request_idempotency_key == ""
    assert snapshot.generation_scope == "SINGLE_TOPIC"
    assert snapshot.source_interest_id == ""
    assert snapshot.interest_profile_id == ""
    assert snapshot.bundle_keywords == []
    assert snapshot.cover_image is None


def test_snapshot_save_payload_preserves_interest_bundle_fields() -> None:
    """생성 결과 저장 경로가 범주 메타데이터를 JSON Payload에서 누락하지 않는다."""
    from app.schemas.mvp import PublishSnapshotResponse
    from infrastructure.persistence.postgres_publish_snapshots import (
        PostgresPublishSnapshotRepository,
    )

    snapshot = PublishSnapshotResponse(
        content_id="content-1",
        user_id="user-1",
        version=1,
        snapshot_hash="h" * 64,
        title="제목",
        summary="요약",
        body="본문",
        generation_scope="INTEREST_BUNDLE",
        source_interest_id="interest-1",
        interest_profile_id="profile-1",
        bundle_keywords=["생성형 AI", "RAG"],
        request_idempotency_key="interest-bundle:2026-08-10:user-1:interest-1",
        cover_image={
            "url": "https://cdn.example/cover.jpg",
            "source_url": "https://news.example/article",
            "source_title": "기사",
            "reference": "G1",
        },
        created_at=datetime(2026, 8, 7, tzinfo=UTC),
    )

    payload = PostgresPublishSnapshotRepository._payload_from_snapshot(snapshot)

    assert (
        payload["request_idempotency_key"]
        == "interest-bundle:2026-08-10:user-1:interest-1"
    )
    assert payload["generation_scope"] == "INTEREST_BUNDLE"
    assert payload["source_interest_id"] == "interest-1"
    assert payload["interest_profile_id"] == "profile-1"
    assert payload["bundle_keywords"] == ["생성형 AI", "RAG"]
    assert payload["cover_image"] == {
        "url": "https://cdn.example/cover.jpg",
        "source_url": "https://news.example/article",
        "source_title": "기사",
        "reference": "G1",
    }


def _run_metadata(connection: _FakeConnection) -> dict[str, Any]:
    """기록된 질의에서 generation_runs INSERT의 run_metadata를 꺼낸다."""
    for sql, params in connection.executed:
        if "INSERT INTO agent.generation_runs" in sql:
            assert params is not None
            return params[4].obj  # Jsonb로 감싼 run_metadata
    raise AssertionError("generation_runs INSERT를 찾지 못했다.")


def test_run_metadata_records_the_critic_verdict() -> None:
    """검토자 판정을 생성 Run에 남긴다.

    검토자는 실패해도 발행을 막지 않으므로, 결과물만 봐서는 "검토를 통과했다"와
    "검토가 실패해 그냥 나갔다"를 구분할 수 없다(2026-08-05 실측: 인용이 엉뚱한
    리포트가 발행됐는데 검토자가 돌았는지조차 로그 없이는 알 수 없었다).
    """
    connection = _connection_for_persist("반도체")

    asyncio.run(
        persist_report_generation(
            connection,  # type: ignore[arg-type]
            job_id="job-1",
            user_id="user-1",
            attempt_number=1,
            content_type="interest_news_card",
            generated=GeneratedReportContent(
                title="제목",
                summary="요약",
                body="본문",
                citation_references=(),
            ),
            contexts=[],
            latency_ms=100,
            review_outcome="unavailable",
        )
    )

    assert _run_metadata(connection)["review_outcome"] == "unavailable"


def test_run_metadata_keeps_review_outcome_empty_when_not_given() -> None:
    """판정을 넘기지 않으면 빈 값으로 남긴다(이 필드 도입 이전 생성분과 같은 모양)."""
    connection = _connection_for_persist("반도체")

    _persist(connection)

    assert _run_metadata(connection)["review_outcome"] == ""


def test_run_metadata_records_what_the_critic_objected_to() -> None:
    """검토자 지적 문장도 함께 남긴다.

    결과 코드(revise_exhausted)만으로는 "무엇을 끝내 고치지 못했는지"를 알 수
    없어 로그를 뒤져야 했다(2026-08-05 실측: 같은 진단에 반나절이 들었다).
    """
    connection = _connection_for_persist("프로야구")

    asyncio.run(
        persist_report_generation(
            connection,  # type: ignore[arg-type]
            job_id="job-1",
            user_id="user-1",
            attempt_number=1,
            content_type="interest_news_card",
            generated=GeneratedReportContent(
                title="제목",
                summary="요약",
                body="본문",
                citation_references=(),
            ),
            contexts=[],
            latency_ms=100,
            review_outcome="revise_exhausted",
            review_problem="인용한 G2 원문은 코스피 상승에 관한 내용이다.",
        )
    )

    metadata = _run_metadata(connection)
    assert metadata["review_outcome"] == "revise_exhausted"
    assert metadata["review_problem"] == "인용한 G2 원문은 코스피 상승에 관한 내용이다."


def test_run_metadata_records_context_role_and_knowledge_time() -> None:
    """생성 Run이 Wiki Context의 역할과 지식 기준 시각을 재현 가능하게 남긴다."""
    connection = _connection_for_persist("생성형 AI")
    context = ReportContextDocument(
        reference="P1",
        document_version_id="version-1",
        chunk_id="chunk-1",
        namespace_key="user/user-1",
        title="생성형 AI",
        content="사용자가 저장한 기존 지식",
        url=None,
        score=1.0,
        context_role="wiki_root",
        source_updated_at="2026-08-09T10:00:00+00:00",
    )

    asyncio.run(
        persist_report_generation(
            connection,  # type: ignore[arg-type]
            job_id="job-1",
            user_id="user-1",
            attempt_number=1,
            content_type="interest_news_card",
            generated=GeneratedReportContent(
                title="제목",
                summary="요약",
                body="본문",
                citation_references=(),
            ),
            contexts=[context],
            latency_ms=100,
        )
    )

    assert _run_metadata(connection)["retrieval_contexts"] == [
        {
            "reference": "P1",
            "namespace_key": "user/user-1",
            "context_role": "wiki_root",
            "source_updated_at": "2026-08-09T10:00:00+00:00",
        }
    ]


def test_stale_context_error_carries_the_current_version() -> None:
    """거절 시 현재 저장된 버전을 함께 알려준다.

    Service는 자기 카운터로 버전을 매기는데 그 카운터가 Agent와 독립이라, 한 번
    어긋나면 무엇을 보내도 계속 거절된다. 현재 값을 주면 받은 값 + 1로 재전송해
    한 번에 수렴한다(2026-08-06: Service가 이 409를 "이미 최신"으로 삼켜 온보딩
    관심사가 전달되지 않는데도 아무도 알지 못했다).
    """
    from infrastructure.persistence.features.generation_runtime import (
        StaleContextVersionError,
    )

    connection = _FakeConnection([[], [{"context_version": 7}]])

    with pytest.raises(StaleContextVersionError) as caught:
        asyncio.run(
            upsert_user_context_snapshot(
                connection,  # type: ignore[arg-type]
                user_id="user-1",
                context_version=4,
                plan="free",
                preferred_language="ko",
                personalization_enabled=True,
                interest_taxonomy_version=None,
                selected_category_ids=[],
                selected_topic_ids=[],
                blocked_interest_ids=[],
                blocked_source_ids=[],
            )
        )

    assert caught.value.current_context_version == 7
    assert caught.value.user_id == "user-1"
