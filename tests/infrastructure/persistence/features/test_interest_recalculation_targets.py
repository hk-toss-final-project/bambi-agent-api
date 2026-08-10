"""관심사 주기 재계산 대상 조회(SCH-010 입력)를 검증한다."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, AsyncIterator

import pytest

from infrastructure.persistence.features.interest_profiles import (
    list_users_for_interest_recalculation,
)


class _FakeCursor:
    """fetchall만 지원하는 결정적 Cursor Test Double."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        """조회 시 반환할 고정 Row 목록을 보관한다."""
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        """전체 Row 목록을 반환한다."""
        return self._rows


class _FakeConnection:
    """Transaction과 SQL 실행을 기록하는 Connection Test Double."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        """고정 Row와 빈 실행 내역을 초기화한다."""
        self._rows = rows
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """실제 커넥션처럼 Transaction 컨텍스트를 제공한다."""
        yield None

    async def execute(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> _FakeCursor:
        """SQL을 기록하고 고정 Cursor를 반환한다."""
        self.executed.append((query, params))
        return _FakeCursor(self._rows)


def test_returns_users_in_query_order() -> None:
    """조회 결과 순서를 그대로 재계산 대상 순서로 반환한다."""
    connection = _FakeConnection([{"user_id": "user-2"}, {"user_id": "user-1"}])

    users = asyncio.run(
        list_users_for_interest_recalculation(
            connection,  # type: ignore[arg-type]
            stale_after_hours=24,
            limit=10,
        )
    )

    assert users == ["user-2", "user-1"]


def test_query_scopes_to_active_wiki_and_stale_profiles() -> None:
    """활성 Wiki가 있고 Profile이 오래된 사용자만 대상으로 조회한다."""
    connection = _FakeConnection([])

    asyncio.run(
        list_users_for_interest_recalculation(
            connection,  # type: ignore[arg-type]
            stale_after_hours=24,
            limit=5,
            now=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        )
    )

    query, params = connection.executed[-1]
    assert "wiki.status = 'active'" in query
    assert "profile.status = 'active'" in query
    assert "profile.calculated_at IS NULL" in query
    assert "NULLS FIRST" in query
    # 기준 시각에서 stale_after_hours를 뺀 시점이 컷오프로 넘어가야 한다.
    assert params == (datetime(2026, 8, 9, 12, 0, tzinfo=UTC), 5)


def test_sets_system_scope_before_cross_user_query() -> None:
    """사용자 경계를 넘는 조회 전에 RLS 시스템 Scope를 설정한다."""
    connection = _FakeConnection([])

    asyncio.run(
        list_users_for_interest_recalculation(
            connection,  # type: ignore[arg-type]
            stale_after_hours=1,
            limit=1,
        )
    )

    assert "app.access_scope = 'system'" in connection.executed[0][0]


def test_rejects_invalid_policy_values() -> None:
    """음수 경과 시간과 1 미만 limit은 조회 전에 거절한다."""
    connection = _FakeConnection([])

    with pytest.raises(ValueError, match="stale_after_hours"):
        asyncio.run(
            list_users_for_interest_recalculation(
                connection,  # type: ignore[arg-type]
                stale_after_hours=-1,
                limit=10,
            )
        )
    with pytest.raises(ValueError, match="limit"):
        asyncio.run(
            list_users_for_interest_recalculation(
                connection,  # type: ignore[arg-type]
                stale_after_hours=24,
                limit=0,
            )
        )
