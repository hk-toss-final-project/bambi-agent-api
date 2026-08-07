"""관심사 범주 묶음 PostgreSQL 저장소를 검증한다."""

import asyncio
from typing import Any

from infrastructure.persistence.features.interest_bundles import (
    ConnectionInterestBundleRepository,
)


class _Cursor:
    """순서별 Row를 반환하는 Cursor 대역."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        """반환할 Row 목록을 보관한다."""
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        """첫 번째 Row 또는 None을 반환한다."""
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        """전체 Row를 반환한다."""
        return self._rows


class _Connection:
    """SQL과 파라미터를 기록하는 연결 대역."""

    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        """순서별 응답과 빈 실행 기록을 초기화한다."""
        self._responses = responses
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, params: tuple[Any, ...]) -> _Cursor:
        """SQL을 기록하고 다음 고정 응답을 반환한다."""
        self.executed.append((query, params))
        return _Cursor(self._responses.pop(0))


def test_repository_loads_only_active_unblocked_interest() -> None:
    """사용자 활성 Profile과 비차단 조건을 SQL에 강제한다."""
    connection = _Connection(
        [[{"profile_id": "profile-1", "profile_version": 3, "topic": "코스피"}]]
    )
    repository = ConnectionInterestBundleRepository(connection)  # type: ignore[arg-type]

    row = asyncio.run(repository.load_active_interest("user-1", "interest-1"))

    query, params = connection.executed[0]
    assert row is not None and row["profile_id"] == "profile-1"
    assert "profile.status = 'active'" in query
    assert "NOT interest.is_blocked" in query
    assert "array_agg(DISTINCT evidence.document_id::text)" in query
    assert params == ("user-1", "interest-1")


def test_repository_orders_one_hop_neighbors_by_evidence_strength() -> None:
    """1홉·조직 제외·공동 원문·degree 정렬과 상한을 조회에 반영한다."""
    connection = _Connection(
        [
            [
                {
                    "document_id": "neighbor-1",
                    "keyword": "코스닥시장",
                    "document_kind": "entity",
                    "weight": 1.0,
                    "relation_types": ["entity_relation"],
                    "shared_source_count": 2,
                    "degree": 4.0,
                }
            ]
        ]
    )
    repository = ConnectionInterestBundleRepository(connection)  # type: ignore[arg-type]

    rows = asyncio.run(
        repository.list_related_nodes(
            "user-1", document_ids=["root-1"], limit=2
        )
    )

    query, params = connection.executed[0]
    assert rows[0]["keyword"] == "코스닥시장"
    assert "document.id = ANY(%s::uuid[])" in query
    assert "COALESCE(peer.domain, '') <> 'organization'" in query
    assert "peer.id NOT IN (SELECT id FROM origin)" in query
    assert "shared_source_count DESC" in query
    assert "degree DESC" in query
    assert params == (
        ["root-1"],
        "user/user-1",
        "user/user-1",
        "user/user-1",
        "user/user-1",
        "user/user-1",
        2,
    )


def test_repository_skips_neighbor_query_without_roots() -> None:
    """근거 문서가 없으면 불필요한 Wiki 관계 조회를 하지 않는다."""
    connection = _Connection([])
    repository = ConnectionInterestBundleRepository(connection)  # type: ignore[arg-type]

    rows = asyncio.run(
        repository.list_related_nodes("user-1", document_ids=[], limit=2)
    )

    assert rows == []
    assert connection.executed == []
