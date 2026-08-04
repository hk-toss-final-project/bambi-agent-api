"""Report Builder Generation Job 등록의 예약 시각(scheduled_at) 영속화를 검증한다."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from infrastructure.persistence.features.generation_runtime import (
    enqueue_report_generation_job,
    persist_report_generation,
    upsert_user_context_snapshot,
)
from shared.report_models import GeneratedReportContent


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
        """SQL을 기록하고 순서별 고정 Cursor를 반환한다."""
        self.executed.append((query, params))
        rows = self._responses.pop(0) if self._responses else []
        return _FakeCursor(rows)


def _connection_with_context() -> _FakeConnection:
    """Context 조회, Job·생성 요청 INSERT 순서의 응답을 준비한다."""
    return _FakeConnection(
        [
            [{"id": "context-1", "plan": "free", "preferred_language": "ko"}],
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
    insert_sql, insert_params = connection.executed[1]
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

    _, insert_params = connection.executed[1]
    assert insert_params is not None and insert_params[-1] is None


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


def _connection_for_persist(topic: str) -> _FakeConnection:
    """인용 없는 리포트 저장 경로가 실행할 질의 순서대로 응답을 준비한다."""
    return _FakeConnection(
        [
            [{"id": "request-1", "topic": topic}],  # generation_requests 조회
            [],  # status = running
            [{"id": "run-1"}],  # generation_runs INSERT
            [{"next_version": 1}],  # 다음 content 버전
            [],  # 이전 후보 superseded
            [{"id": "cand-1", "created_at": datetime(2026, 7, 30, tzinfo=UTC)}],
            [],  # generation_runs completed
            [],  # generation_requests completed
            [],  # publish_snapshots INSERT
            [],  # event_outbox INSERT
        ]
    )


def _publish_payload(connection: _FakeConnection) -> dict[str, Any]:
    """기록된 질의에서 publish_snapshots INSERT의 payload를 꺼낸다."""
    for sql, params in connection.executed:
        if "INSERT INTO agent.publish_snapshots" in sql:
            assert params is not None
            return params[5].obj  # Jsonb로 감싼 payload
    raise AssertionError("publish_snapshots INSERT를 찾지 못했다.")


def _persist(connection: _FakeConnection) -> None:
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


def test_publish_payload_omits_blank_topic_tag() -> None:
    """공백뿐인 topic은 빈 태그로 노출되지 않도록 제외한다."""
    connection = _connection_for_persist("   ")

    _persist(connection)

    assert _publish_payload(connection)["tags"] == []
