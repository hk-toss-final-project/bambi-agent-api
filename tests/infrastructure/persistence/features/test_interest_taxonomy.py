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

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """Transaction 문맥을 흉내 낸다."""
        yield

    async def execute(self, query: str, params: tuple[Any, ...] = ()) -> _FakeCursor:
        """SQL과 Parameter를 기록하고 다음 준비 Row를 반환한다."""
        self.executed.append((query, params))
        return _FakeCursor(self._rows.pop(0) if self._rows else None)


def _connection(*, existing_targets: list[dict[str, Any]] | None = None) -> _FakeConnection:
    """컨텍스트 Snapshot 조회와 기존 수집 대상 조회 응답을 준비한다."""
    return _FakeConnection(
        [
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
    connection = _FakeConnection([[]])

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
