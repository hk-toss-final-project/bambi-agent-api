"""infrastructure/persistence/features/interest_taxonomy.py의 수집 대상 동기화를 검증한다.

개인 Wiki 상위 관심사를 창고 수집 대상으로 자동 등록하는 경로가 대상이다.
창고를 채우는 말(온보딩 taxonomy 라벨)과 관심사를 뽑는 말(Wiki 노드 제목)이
달라서, 이 등록이 없으면 사용자가 실제로 파고든 주제일수록 리포트가 근거를
찾지 못한다.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from infrastructure.persistence.features.interest_taxonomy import (
    _reconcile_collection_target_policy,
    _scaled_collection_refresh_intervals,
    sync_wiki_interest_collection_targets,
)


class _FakeCursor:
    """이 실행에 대응하는 고정 Row를 반환하는 Cursor Test Double."""

    def __init__(self, row: Any) -> None:
        """반환할 Row를 보관한다."""
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
        self.executed_many: list[
            tuple[str, list[tuple[int, str, int, str]]]
        ] = []
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

    async def executemany(
        self, query: str, params: list[tuple[int, str, int, str]]
    ) -> None:
        """Batch SQL과 Parameter 목록을 기록한다."""
        self.executed_many.append((query, params))


def _connection(*, existing_targets: list[dict[str, Any]] | None = None) -> _FakeConnection:
    """컨텍스트 Snapshot 조회와 기존 수집 대상 조회 응답을 준비한다."""
    return _FakeConnection(
        [
            None,  # SET LOCAL app.access_scope
            [{"id": "context-1"}],  # 최신 컨텍스트 Snapshot
            existing_targets or [],  # 같은 검색어로 이미 도는 수집 대상
        ]
    )


def _sync(connection: _FakeConnection, interests: list[dict[str, Any]], **kwargs: Any) -> list[str]:
    """동기화를 실행하고 구독한 주제 목록을 돌려준다."""
    return asyncio.run(
        sync_wiki_interest_collection_targets(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            interests=interests,
            **kwargs,
        )
    )


def _statements(connection: _FakeConnection, fragment: str) -> list[tuple[str, tuple[Any, ...]]]:
    """실행 기록에서 특정 SQL 조각을 포함한 것만 추린다."""
    return [(sql, params) for sql, params in connection.executed if fragment in sql]


def test_top_interests_become_collection_targets() -> None:
    """상위 관심사가 custom 수집 대상으로 등록되고 구독까지 만들어진다."""
    connection = _connection()

    subscribed = _sync(
        connection,
        [
            {"topic": "오스틴딘", "score": 1.0},
            {"topic": "SK하이닉스", "score": 0.7},
        ],
    )

    assert subscribed == ["오스틴딘", "SK하이닉스"]
    inserts = _statements(connection, "INSERT INTO agent.interest_collection_targets")
    assert [params[1] for _, params in inserts] == ["오스틴딘", "SK하이닉스"]
    subscriptions = _statements(
        connection, "INSERT INTO agent.user_interest_subscriptions"
    )
    assert len(subscriptions) == 2
    # 온보딩 구독과 섞이지 않도록 출처를 남긴다.
    assert all("'wiki_interest'" in sql for sql, _ in subscriptions)


def test_low_scoring_interests_are_not_collected() -> None:
    """점수 하한 아래 관심사는 창고가 따라가지 않는다.

    한 번 저장하고 만 주제까지 수집 대상이 되면 외부 API 한도만 먹는다.
    """
    connection = _connection()

    subscribed = _sync(
        connection,
        [{"topic": "오스틴딘", "score": 1.0}, {"topic": "스쳐간 주제", "score": 0.05}],
    )

    assert subscribed == ["오스틴딘"]


def test_non_subject_wiki_nodes_are_not_collection_targets() -> None:
    """도구·출처·단순 언급 노드는 점수가 높아도 뉴스 검색어로 등록하지 않는다."""
    connection = _connection()

    subscribed = _sync(
        connection,
        [
            {
                "topic": "DBeaver Community",
                "score": 1.0,
                "evidence": {"interest_subject": False},
            },
            {
                "topic": "PostgreSQL 인덱스",
                "score": 0.8,
                "evidence": {"interest_subject": True},
            },
        ],
    )

    assert subscribed == ["PostgreSQL 인덱스"]


def test_legacy_interest_without_role_judgment_remains_collectable() -> None:
    """역할 판정이 없던 기존 관심사는 재빌드 전에도 수집을 유지한다."""
    connection = _connection()

    subscribed = _sync(connection, [{"topic": "기존 관심사", "score": 1.0}])

    assert subscribed == ["기존 관심사"]


def test_registration_is_capped() -> None:
    """관심사가 많아도 상한까지만 등록한다."""
    connection = _connection()

    subscribed = _sync(
        connection,
        [{"topic": f"주제{index}", "score": 1.0} for index in range(10)],
        limit=3,
    )

    assert subscribed == ["주제0", "주제1", "주제2"]


def test_existing_target_is_reused_instead_of_duplicated() -> None:
    """같은 검색어로 이미 도는 수집 대상이 있으면 새로 만들지 않고 구독만 한다.

    같은 말로 두 번 수집하면 외부 API 호출만 두 배가 된다.
    """
    connection = _connection(
        existing_targets=[
            {"target_key": "taxonomy:v1:baseball", "normalized_query": "프로야구"}
        ]
    )

    subscribed = _sync(connection, [{"topic": "프로야구", "score": 1.0}])

    assert subscribed == ["프로야구"]
    assert _statements(connection, "INSERT INTO agent.interest_collection_targets") == []
    subscriptions = _statements(
        connection, "INSERT INTO agent.user_interest_subscriptions"
    )
    assert len(subscriptions) == 1
    assert subscriptions[0][1][1] == "taxonomy:v1:baseball"


def test_sync_is_skipped_without_a_user_context() -> None:
    """컨텍스트가 아직 없는 사용자는 조용히 건너뛴다.

    구독 행이 컨텍스트 Snapshot을 참조하므로 만들 수 없다. 관심사 재계산
    자체를 실패시킬 이유는 없다.
    """
    connection = _FakeConnection([None, []])

    subscribed = _sync(connection, [{"topic": "오스틴딘", "score": 1.0}])

    assert subscribed == []
    assert _statements(connection, "INSERT INTO agent.user_interest_subscriptions") == []


def test_previous_wiki_interest_subscriptions_are_deactivated() -> None:
    """관심사가 바뀌면 이전 자동 구독은 끄고 새로 넣는다.

    끄지 않으면 한 번 상위였던 주제를 영원히 수집한다. 온보딩 구독은
    건드리지 않는다.
    """
    connection = _connection()

    _sync(connection, [{"topic": "오스틴딘", "score": 1.0}])

    deactivations = _statements(connection, "SET active = false")
    assert len(deactivations) == 1
    assert "origin = 'wiki_interest'" in deactivations[0][0]


def test_collection_refresh_intervals_follow_subscriber_tiers() -> None:
    """구독 1~4명은 하루, 5~9명은 12시간, 10명 이상은 6시간마다 수집한다."""
    assert _scaled_collection_refresh_intervals([1, 4, 5, 9, 10, 20]) == [
        1440,
        1440,
        720,
        720,
        360,
        360,
    ]


def test_collection_refresh_intervals_stay_within_daily_capacity() -> None:
    """대상이 늘면 모든 주기를 늘려 하루 예상 수요를 250회 이하로 맞춘다."""
    intervals = _scaled_collection_refresh_intervals([1] * 300)

    assert sum(1440.0 / interval for interval in intervals) <= 250
    assert set(intervals) == {1728}


def test_collection_target_policy_pauses_and_reactivates_by_subscribers() -> None:
    """0명은 중지하고 구독이 생긴 대상은 구독자 수에 맞는 주기로 되살린다."""
    connection = _FakeConnection(
        [
            None,  # 전역 정책 advisory lock
            [
                {
                    "target_key": "zero",
                    "status": "active",
                    "subscriber_count": 3,
                    "refresh_interval_minutes": 360,
                    "actual_subscriber_count": 0,
                },
                {
                    "target_key": "one",
                    "status": "paused",
                    "subscriber_count": 0,
                    "refresh_interval_minutes": 360,
                    "actual_subscriber_count": 1,
                },
                {
                    "target_key": "five",
                    "status": "active",
                    "subscriber_count": 5,
                    "refresh_interval_minutes": 360,
                    "actual_subscriber_count": 5,
                },
                {
                    "target_key": "ten",
                    "status": "active",
                    "subscriber_count": 10,
                    "refresh_interval_minutes": 360,
                    "actual_subscriber_count": 10,
                },
                {
                    "target_key": "retired",
                    "status": "retired",
                    "subscriber_count": 0,
                    "refresh_interval_minutes": 360,
                    "actual_subscriber_count": 1,
                },
            ],
        ]
    )

    asyncio.run(
        _reconcile_collection_target_policy(connection)  # type: ignore[arg-type]
    )

    assert len(connection.executed_many) == 1
    assert sorted(connection.executed_many[0][1], key=lambda item: item[3]) == [
        (5, "active", 720, "five"),
        (1, "active", 1440, "one"),
        (1, "retired", 360, "retired"),
        (0, "paused", 360, "zero"),
    ]


def test_sync_runs_in_its_own_system_scope_transaction() -> None:
    """수집 대상 쓰기를 자기 Transaction + system scope 안에서 수행한다.

    수집 대상 쓰기는 RLS가 system scope를 요구하는데, 이 함수는 Wiki Build 직후
    user scope 커넥션에서 불린다. 감싸지 않으면 INSERT가 RLS에 막히고 커넥션이
    실패 상태가 되어, 호출자가 이어서 하는 Job 완료 기록까지 막힌다
    (2026-08-06 실측: 노드는 저장됐는데 Job이 완료로 넘어가지 못해 재실행이 반복).
    """
    connection = _connection()

    _sync(connection, [{"topic": "오스틴딘", "score": 1.0}])

    assert connection.transactions == 1
    scope_statements = _statements(connection, "app.access_scope")
    assert len(scope_statements) == 1
    assert "'system'" in scope_statements[0][0]
    # scope 설정이 DB 접근보다 먼저 와야 한다.
    assert connection.executed[0][0] == scope_statements[0][0]


def test_sync_clears_previous_subscriptions_without_candidates() -> None:
    """등록할 관심사가 없어도 이전 자동 구독을 꺼 수집 대상을 정리한다."""
    connection = _connection()

    subscribed = _sync(connection, [{"topic": "스쳐간 주제", "score": 0.01}])

    assert subscribed == []
    assert connection.transactions == 1
    deactivations = _statements(connection, "SET active = false")
    assert len(deactivations) == 1
    assert "origin = 'wiki_interest'" in deactivations[0][0]
