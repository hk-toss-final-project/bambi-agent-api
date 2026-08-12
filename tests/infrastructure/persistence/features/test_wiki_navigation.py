"""LLM Wiki Navigator 조회 SQL을 검증한다.

관계 조회는 집계(jsonb_agg)를 쓰므로 GROUP BY 구성이 스키마와 맞아야 한다.
어긋나면 PostgreSQL이 GroupingError를 내고, 호출자(packet.py)가 예외를 삼켜
Seed Page만 쓰게 된다 — 오류 없이 근거만 얇아지므로 눈에 띄지 않는다.
"""

import asyncio
from typing import Any

from infrastructure.persistence.features.wiki_navigation import (
    load_wiki_navigation_relations,
)


class _FakeCursor:
    """fetchall만 지원하는 결정적 Cursor Test Double."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        """반환할 Row 목록을 보관한다."""
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        """준비된 Row를 그대로 반환한다."""
        return self._rows


class _FakeConnection:
    """실행한 SQL과 파라미터를 기록하는 Connection Test Double."""

    def __init__(self) -> None:
        """빈 실행 내역을 초기화한다."""
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    async def execute(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> _FakeCursor:
        """SQL을 기록하고 빈 Cursor를 반환한다."""
        self.executed.append((query, params))
        return _FakeCursor([])


def test_relation_query_groups_by_primary_key() -> None:
    """관계 조회가 기본키로 묶는지 검증한다.

    PostgreSQL은 **기본키로만** 함수 종속을 인정한다. 이 테이블의 기본키는
    (source_document_id, target_document_id, relation_type)이고 id는
    (id, namespace_key) UNIQUE라, `GROUP BY relation.id`로는 나머지
    relation.* 컬럼을 SELECT할 수 없다(2026-08-12 실측: 이 쿼리가 항상
    실패해 Navigator 관계 탐색이 통째로 건너뛰어지고 있었다).
    """
    connection = _FakeConnection()

    asyncio.run(
        load_wiki_navigation_relations(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            document_ids=["doc-1"],
        )
    )

    query, _ = connection.executed[0]
    grouping = query.split("GROUP BY", 1)[1].split("ORDER BY", 1)[0]
    assert "relation.source_document_id" in grouping
    assert "relation.target_document_id" in grouping
    assert "relation.relation_type" in grouping


def test_relation_query_skips_db_call_without_documents() -> None:
    """조회할 Page가 없으면 SQL을 실행하지 않는다."""
    connection = _FakeConnection()

    result = asyncio.run(
        load_wiki_navigation_relations(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            document_ids=[],
        )
    )

    assert result == []
    assert connection.executed == []
