"""변경점(Delta) 추적 팩트 영속화의 조회·저장 계약을 검증한다.

DB 없이 결정적으로 돌아야 하므로 Connection Test Double을 쓴다. 확인하는 것은
세 가지다 — (1) 모든 조회가 user_id와 topic 둘 다로 격리되는가, (2) 첫 실행에도
팩트가 저장되는가, (3) 갱신 시 과거 팩트를 지우지 않고 superseded로 내리는가.
"""

import asyncio
from datetime import date
from typing import Any

from infrastructure.persistence.features.change_history_facts import (
    load_change_history_facts_by_ids,
    load_latest_change_history_run,
    load_latest_report_snapshot,
    persist_change_history_run,
    search_change_history_facts,
)
from shared.change_history_models import NewChangeHistoryFact


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
        `%%`(trigram 연산자 escape)는 자리표시자가 아니므로 세지 않는다.
        """
        placeholders = query.replace("%%", "").count("%s")
        if params is not None and placeholders != len(params):
            raise AssertionError(
                f"자리표시자 {placeholders}개와 파라미터 {len(params)}개가 다릅니다."
            )
        self.executed.append((query, params))
        rows = self._responses.pop(0) if self._responses else []
        return _FakeCursor(rows)


def _fact_row(fact_id: str, *, subject: str, value: str) -> dict[str, Any]:
    """조회 응답으로 쓸 팩트 Row를 만든다."""
    return {
        "id": fact_id,
        "subject": subject,
        "attribute": "양산 일정",
        "fact_value": value,
        "statement": f"{subject}의 양산 일정은 {value}이다.",
        "verdict": "new",
        "occurred_on": date(2026, 8, 1),
        "date_precision": "day",
        "source_reference": "G1",
        "source_url": "https://example.test/a",
    }


def test_search_facts_filters_by_user_and_topic() -> None:
    """도구 조회가 user_id와 topic 두 조건으로 격리되는지 검증한다."""
    connection = _FakeConnection([[_fact_row("11111111-1111-4111-8111-111111111111", subject="B사 HBM4", value="2026-2Q")]])

    facts = asyncio.run(
        search_change_history_facts(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
            query="HBM4",
        )
    )

    query, params = connection.executed[0]
    assert "user_id = %s" in query
    assert "topic = %s" in query
    assert "status = 'active'" in query
    assert params is not None and params[0] == "user-1" and params[1] == "반도체"
    assert facts[0].subject == "B사 HBM4"
    assert facts[0].fact_value == "2026-2Q"


def test_search_ranks_instead_of_filtering_by_similarity_threshold() -> None:
    """검색이 유사도 **임계값으로 거르지 않고** 관련도 순으로 정렬만 하는지 고정한다.

    이 저장소의 테스트는 Connection을 대역으로 쓰므로 SQL의 **의미**는 실행되지
    않는다. 그래서 임계값 방식이 조용히 실패하는 것을 두 번이나 놓쳤다
    (2026-08-06 실측).

      1. `%`(similarity): '코스피' vs 코스피 팩트 = 0.093 (임계값 0.3 미달)
      2. `<%`(word_similarity): '코스닥 상승폭 28%' = 0.36 (임계값 0.6 미달)

    두 경우 모두 팩트가 DB에 있는데도 도구가 "과거 기록 없음"을 돌려줘, 중복·
    갱신 판정이 통째로 죽었다. **팩트가 있는데 빈 결과를 주는 것**이 이 기능에서
    가장 해로운 실패이므로 필터 자체를 두지 않는다.
    """
    connection = _FakeConnection([[]])

    asyncio.run(
        search_change_history_facts(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
            query="코스닥 상승폭 28%",
        )
    )

    query, params = connection.executed[0]
    # 관련도는 정렬에만 쓴다.
    assert "ORDER BY" in query
    assert "word_similarity(" in query
    # 유사도 연산자로 행을 걸러내면 임계값 미달 검색어가 다시 빈손이 된다.
    assert "<%%" not in query, "유사도 연산자로 필터링하면 안 된다(정렬만 한다)"
    assert "%% %s" not in query, "similarity 연산자로 필터링하면 안 된다"
    # 격리 조건은 그대로 유지돼야 한다.
    assert "user_id = %s" in query and "topic = %s" in query
    assert params is not None and params[:2] == ("user-1", "반도체")


def test_search_facts_returns_empty_for_blank_query() -> None:
    """빈 검색어는 DB를 건드리지 않고 빈 목록을 돌려준다."""
    connection = _FakeConnection([])

    facts = asyncio.run(
        search_change_history_facts(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
            query="   ",
        )
    )

    assert facts == []
    assert connection.executed == []


def test_load_facts_by_ids_drops_non_uuid_values() -> None:
    """UUID가 아닌 ID는 조회 전에 걸러 psycopg 타입 오류를 막는다."""
    connection = _FakeConnection([[]])

    asyncio.run(
        load_change_history_facts_by_ids(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
            fact_ids=["P1", "", "22222222-2222-4222-8222-222222222222"],
        )
    )

    _, params = connection.executed[0]
    assert params is not None
    assert params[2] == ["22222222-2222-4222-8222-222222222222"]


def test_load_facts_by_ids_skips_query_when_all_ids_invalid() -> None:
    """쓸 수 있는 ID가 하나도 없으면 조회 없이 빈 사전을 반환한다."""
    connection = _FakeConnection([])

    found = asyncio.run(
        load_change_history_facts_by_ids(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
            fact_ids=["없는 팩트", "G2"],
        )
    )

    assert found == {}
    assert connection.executed == []


def test_persist_stores_facts_on_first_run() -> None:
    """비교 대상이 없는 첫 실행에서도 팩트를 저장해 다음 Base를 만든다."""
    connection = _FakeConnection(
        [
            [{"id": "33333333-3333-4333-8333-333333333333"}],  # run INSERT
            [{"id": "44444444-4444-4444-8444-444444444444"}],  # fact INSERT
        ]
    )

    persisted = asyncio.run(
        persist_change_history_run(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
            reference_date=date(2026, 8, 5),
            is_first_run=True,
            facts=[
                NewChangeHistoryFact(
                    subject="B사 HBM4",
                    attribute="양산 일정",
                    fact_value="2026-3Q",
                    statement="B사가 HBM4 양산을 2026-3Q로 연기했다.",
                    verdict="new",
                )
            ],
        )
    )

    assert persisted.run_id == "33333333-3333-4333-8333-333333333333"
    assert persisted.fact_ids == ("44444444-4444-4444-8444-444444444444",)
    run_query, run_params = connection.executed[0]
    assert "INSERT INTO agent.change_history_runs" in run_query
    assert run_params is not None and run_params[6] is True  # is_first_run
    assert "INSERT INTO agent.change_history_facts" in connection.executed[1][0]


def test_persist_marks_updated_base_fact_as_superseded() -> None:
    """갱신 팩트는 과거 Row를 지우지 않고 superseded로 내린다."""
    base_id = "55555555-5555-4555-8555-555555555555"
    connection = _FakeConnection(
        [
            [{"id": "66666666-6666-4666-8666-666666666666"}],  # run
            [{"id": "77777777-7777-4777-8777-777777777777"}],  # fact
            [],  # supersede UPDATE
        ]
    )

    persisted = asyncio.run(
        persist_change_history_run(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
            reference_date=date(2026, 8, 5),
            facts=[
                NewChangeHistoryFact(
                    subject="B사 HBM4",
                    attribute="양산 일정",
                    fact_value="2026-3Q",
                    statement="B사가 HBM4 양산을 2026-3Q로 연기했다.",
                    verdict="updated",
                    supersedes_fact_id=base_id,
                    before_value="2026-2Q",
                )
            ],
        )
    )

    assert persisted.superseded_fact_ids == (base_id,)
    update_query, update_params = connection.executed[2]
    assert "SET status = 'superseded'" in update_query
    assert "DELETE" not in update_query
    assert update_params == (base_id, "user-1", "반도체")
    _, run_params = connection.executed[0]
    assert run_params is not None and run_params[9] == 1  # updated_fact_count


def test_latest_report_snapshot_reads_topic_from_generation_request() -> None:
    """맥락 요약은 (user_id, topic)의 가장 최근 Snapshot Payload에서 읽는다."""
    connection = _FakeConnection(
        [
            [
                {
                    "payload": {
                        "title": "반도체 주간",
                        "summary": "요약",
                        "body": "본문",
                    },
                    "created_at": "2026-08-04T00:00:00+00:00",
                }
            ]
        ]
    )

    snapshot = asyncio.run(
        load_latest_report_snapshot(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
        )
    )

    query, params = connection.executed[0]
    assert "request.topic = %s" in query
    assert params == ("user-1", "반도체")
    assert snapshot is not None and snapshot.body == "본문"


def test_latest_change_history_run_returns_none_without_history() -> None:
    """직전 실행이 없으면 None을 반환해 호출자가 첫 실행으로 처리하게 한다."""
    connection = _FakeConnection([[]])

    run = asyncio.run(
        load_latest_change_history_run(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
        )
    )

    assert run is None
