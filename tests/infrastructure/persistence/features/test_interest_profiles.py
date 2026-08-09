"""infrastructure/persistence/features/interest_profiles.py의 커넥션 함수를 검증한다."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from infrastructure.persistence.features.interest_profiles import (
    ConnectionInterestProfileRepository,
    load_interest_documents_for_user,
    save_interest_profile_for_user,
)
from shared.wiki_models import InterestCandidate


class _FakeCursor:
    """실행 순서대로 준비된 Row를 반환하는 Cursor Test Double."""

    def __init__(self, row: Any) -> None:
        """이 실행에 대응하는 고정 Row를 보관한다."""
        self._row = row

    async def fetchone(self) -> Any:
        """준비된 Row 하나를 반환한다."""
        if isinstance(self._row, list):
            return self._row[0] if self._row else None
        return self._row

    async def fetchall(self) -> list[Any]:
        """준비된 Row 목록을 반환한다."""
        if self._row is None:
            return []
        return self._row if isinstance(self._row, list) else [self._row]


class _FakeConnection:
    """SQL 실행 내역을 기록하고 실행 순서별 Row를 반환하는 Connection Test Double."""

    def __init__(self, rows: list[Any]) -> None:
        """실행 순서별 반환 Row 큐와 실행 기록을 초기화한다."""
        self._rows = list(rows)
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.transactions = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """열린 Transaction 수를 세는 문맥을 제공한다."""
        self.transactions += 1
        yield

    async def execute(self, query: str, params: tuple[Any, ...] = ()) -> _FakeCursor:
        """SQL과 Parameter를 기록하고 다음 준비 Row를 반환한다."""
        self.executed.append((query, params))
        return _FakeCursor(self._rows.pop(0) if self._rows else None)


def _candidate() -> InterestCandidate:
    """저장 검증에 사용할 관심 후보 하나를 만든다."""
    return InterestCandidate(
        topic="LangGraph",
        category="method",
        score=1.0,
        confidence=0.75,
        document_ids=("doc-1",),
        evidence={"weight": 5.0, "reasons": ["title"]},
    )


def test_load_interest_documents_reads_weighted_relation_and_source_stats() -> None:
    """자동 재계산 입력에 Wiki 구조·원본·최신성 신호를 함께 채운다."""
    last_activity_at = datetime(2026, 7, 27, tzinfo=UTC)
    connection = _FakeConnection(
        [
            None,  # set_personal_wiki_scope
            {"id": "wiki-version-1", "version": 3},
            [
                {
                    "document_id": "doc-1",
                    "document_kind": "entity",
                    "document_key": "langgraph",
                    "domain": "product",
                    "title": "LangGraph",
                    "summary": "그래프 오케스트레이션",
                    "source_metadata": {"aliases": ["랭그래프"]},
                    "degree": 3.5,
                    "source_count": 2,
                    "source_types": ["memo", "web_clipping"],
                    "last_activity_at": last_activity_at,
                }
            ],
        ]
    )

    payload = asyncio.run(
        load_interest_documents_for_user(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
        )
    )

    assert connection.transactions == 1
    assert "set_config" in connection.executed[0][0]
    assert payload["wiki_version_id"] == "wiki-version-1"
    assert payload["wiki_version"] == 3
    documents = payload["documents"]
    assert isinstance(documents, list)
    assert documents[0]["document_id"] == "doc-1"
    assert documents[0]["source_metadata"] == {"aliases": ["랭그래프"]}
    assert documents[0]["degree"] == 3.5
    assert documents[0]["source_count"] == 2
    assert documents[0]["source_types"] == ["memo", "web_clipping"]
    assert documents[0]["last_activity_at"] == last_activity_at

    document_query = connection.executed[2][0]
    assert "FROM agent.wiki_document_relations AS relation" in document_query
    assert "WHEN 'related_concept' THEN 0.5" in document_query
    assert "WHEN 'subtopic_of' THEN 1.0" in document_query
    assert "WHEN 'associated_with' THEN 0.5" in document_query
    assert "relation.status = 'active'" in document_query
    assert "relation.review_status <> 'rejected'" in document_query
    assert "SELECT SUM(neighbor.max_weight) AS degree" in document_query
    assert ") AS max_weight" in document_query
    assert "GROUP BY peer.id" in document_query
    assert "COUNT(DISTINCT source_document.id)" in document_query
    assert "document.document_kind IN ('entity', 'concept')" in document_query
    assert "document.status = 'active'" in document_query


def test_load_interest_documents_collects_onboarding_seed_labels() -> None:
    """시드 Version들의 선택 라벨을 중복 없이 모아 INT-001 입력으로 넘긴다."""
    connection = _FakeConnection(
        [
            None,  # set_personal_wiki_scope
            {"id": "wiki-version-1", "version": 1},
            [],  # 문서 조회
            [
                {"labels": ["생성형 AI", "반도체"]},
                {"labels": ["반도체", "금리"]},
                {"labels": None},
            ],
        ]
    )

    payload = asyncio.run(
        load_interest_documents_for_user(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
        )
    )

    assert payload["onboarding_seed_labels"] == ["생성형 AI", "반도체", "금리"]
    label_query = connection.executed[3][0]
    assert "source_type = 'onboarding_seed'" in label_query
    assert "source_metadata -> 'labels'" in label_query


def test_load_interest_documents_handles_missing_active_wiki() -> None:
    """활성 Wiki가 없으면 Version 정보를 None으로 반환한다."""
    connection = _FakeConnection([None, None, []])

    payload = asyncio.run(
        load_interest_documents_for_user(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
        )
    )

    assert payload["wiki_version_id"] is None
    assert payload["wiki_version"] is None
    assert payload["documents"] == []


def test_save_interest_profile_versions_and_activates_profile() -> None:
    """기존 active를 retire하고 새 Version을 building→active로 저장한다."""
    calculated_at = datetime(2026, 7, 27, tzinfo=UTC)
    connection = _FakeConnection(
        [
            None,  # set_personal_wiki_scope
            None,  # advisory lock
            {"next_version": 4},
            None,  # retire update
            {"id": "profile-1", "calculated_at": calculated_at},
            {"id": "interest-1"},
            None,  # evidence insert
            None,  # activate update
        ]
    )

    payload = asyncio.run(
        save_interest_profile_for_user(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            wiki_version_id="wiki-version-1",
            candidates=[_candidate()],
        )
    )

    assert connection.transactions == 1
    assert payload["profile_id"] == "profile-1"
    assert payload["version"] == 4
    assert payload["status"] == "active"
    interests = payload["interests"]
    assert isinstance(interests, list)
    assert interests[0]["topic"] == "LangGraph"
    assert interests[0]["document_ids"] == ["doc-1"]
    executed_sql = [query for query, _ in connection.executed]
    assert any("pg_advisory_xact_lock" in query for query in executed_sql)
    assert any("SET status = 'retired'" in query for query in executed_sql)
    assert any("SET status = 'active'" in query for query in executed_sql)
    assert any("INSERT INTO agent.interest_evidence" in query for query in executed_sql)


def test_connection_repository_delegates_to_row_functions() -> None:
    """커넥션 어댑터가 저장소 계약 두 메서드를 커넥션 함수로 위임한다."""
    connection = _FakeConnection([None, None, []])
    repository = ConnectionInterestProfileRepository(connection)  # type: ignore[arg-type]

    payload = asyncio.run(repository.load_interest_documents("user-1"))

    assert payload["documents"] == []
    assert connection.transactions == 1


def test_save_feedback_signals_deduplicates_by_event_id() -> None:
    """행동 신호 저장이 source_event_id 중복을 건너뛰는지 검증한다."""
    from infrastructure.persistence.features.interest_profiles import (
        save_feedback_signals_for_user,
    )

    connection = _FakeConnection([None, {"id": "event-1"}, None])

    accepted = asyncio.run(
        save_feedback_signals_for_user(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            signals=[
                {
                    "source_event_id": "signal-1",
                    "signal_type": "like",
                    "topics": ["LangGraph"],
                    "content_id": "content-1",
                    "occurred_at": None,
                    "metadata": {
                        "axis": "topic",
                        "dwell_seconds": 1.8,
                        "scroll_ratio": 0.0,
                        "source": {"surface": "report"},
                    },
                },
                {
                    "source_event_id": "signal-1",
                    "signal_type": "like",
                    "topics": ["LangGraph"],
                    "content_id": None,
                    "occurred_at": None,
                },
            ],
        )
    )

    assert accepted == 1
    insert_sql = connection.executed[1][0]
    assert "'feedback'" in insert_sql
    assert "ON CONFLICT (user_id, source_event_id) DO NOTHING" in insert_sql
    payload = connection.executed[1][1][-1].obj
    assert payload["metadata"] == {
        "axis": "topic",
        "dwell_seconds": 1.8,
        "scroll_ratio": 0.0,
        "source": {"surface": "report"},
    }


def test_load_recent_feedback_signals_flattens_topics() -> None:
    """feedback 이벤트의 topics가 Topic 단위 신호로 펼쳐지는지 검증한다."""
    from datetime import UTC, datetime

    from infrastructure.persistence.features.interest_profiles import (
        load_recent_feedback_signals_for_user,
    )

    occurred = datetime(2026, 7, 27, tzinfo=UTC)
    connection = _FakeConnection(
        [
            None,
            [
                {
                    "payload": {
                        "signal_type": "like",
                        "topics": ["LangGraph", "  ", "Python"],
                        "metadata": {
                            "axis": "angle",
                            "dwell_seconds": 7.25,
                        },
                    },
                    "occurred_at": occurred,
                },
                {"payload": {"signal_type": "", "topics": ["무시"]}, "occurred_at": occurred},
            ],
        ]
    )

    signals = asyncio.run(
        load_recent_feedback_signals_for_user(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
        )
    )

    assert signals == [
        {
            "topic": "LangGraph",
            "signal_type": "like",
            "occurred_at": occurred,
            "metadata": {"axis": "angle", "dwell_seconds": 7.25},
        },
        {
            "topic": "Python",
            "signal_type": "like",
            "occurred_at": occurred,
            "metadata": {"axis": "angle", "dwell_seconds": 7.25},
        },
    ]
