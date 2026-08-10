"""개인 LLM Wiki 계정 단위 초기화 SQL을 검증한다."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from infrastructure.persistence.features.wiki_reset import reset_personal_wiki


class _Transaction:
    """테스트에서 비동기 Transaction 문맥을 흉내 낸다."""

    async def __aenter__(self) -> None:
        """Transaction 진입을 허용한다."""

    async def __aexit__(self, *_: object) -> None:
        """Transaction 종료를 허용한다."""


class _Cursor:
    """고정 Row를 반환하는 Cursor 대역."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        """반환할 Row를 저장한다."""
        self._rows = rows

    async def fetchone(self) -> dict[str, object] | None:
        """첫 Row를 반환한다."""
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, object]]:
        """모든 Row를 반환한다."""
        return self._rows


class _Connection:
    """Query별 예상 반영 건수를 반환하는 PostgreSQL 연결 대역."""

    COUNTS = {
        "UPDATE agent.agent_jobs\n": 2,
        "UPDATE agent.wiki_relation_supports": 3,
        "UPDATE agent.wiki_document_relations": 4,
        "UPDATE agent.wiki_chunks": 5,
        "UPDATE agent.wiki_documents": 6,
        "UPDATE agent.wiki_versions": 1,
        "UPDATE agent.user_interest_profiles": 1,
    }

    def __init__(self) -> None:
        """실행 Query 기록을 초기화한다."""
        self.queries: list[tuple[str, object]] = []

    def transaction(self) -> _Transaction:
        """비동기 Transaction 문맥을 반환한다."""
        return _Transaction()

    async def execute(
        self, query: str, params: object = None
    ) -> _Cursor:
        """Query를 기록하고 종류별 고정 Row를 반환한다."""
        normalized = query.strip()
        self.queries.append((normalized, params))
        if "clock_timestamp() AS reset_at" in normalized:
            return _Cursor([{"reset_at": datetime(2026, 8, 10, tzinfo=UTC)}])
        for marker, count in self.COUNTS.items():
            if marker in normalized:
                return _Cursor([{"id": str(index)} for index in range(count)])
        return _Cursor([])


def test_reset_personal_wiki_deactivates_only_derived_user_state() -> None:
    """초기화가 사용자 원본을 건드리지 않고 파생 상태와 Build를 종료하는지 검증한다."""
    connection = _Connection()

    result = asyncio.run(
        reset_personal_wiki(  # type: ignore[arg-type]
            connection,
            user_id="user-1",
            request_id="request-1",
        )
    )

    assert result == {
        "reset_document_count": 6,
        "reset_relation_count": 4,
        "unsearchable_chunk_count": 5,
        "retired_wiki_version_count": 1,
        "retired_interest_profile_count": 1,
        "cancelled_job_count": 2,
        "reset_at": datetime(2026, 8, 10, tzinfo=UTC),
    }
    sql = "\n".join(query for query, _ in connection.queries)
    assert "pg_advisory_xact_lock" in sql
    assert "job_type = 'personal_wiki_build'" in sql
    assert "source_type" in sql and "'reset'" in sql
    assert "UPDATE agent.user_source" not in sql
    assert "DELETE FROM agent.user_source" not in sql
