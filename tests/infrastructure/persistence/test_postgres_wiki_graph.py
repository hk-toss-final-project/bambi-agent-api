"""PostgreSQL Wiki Graph 조회 Row의 응답 조립을 검증한다."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from app.schemas.wiki import WikiGraphResponse
from infrastructure.persistence.postgres_wiki_graph import (
    PostgresWikiGraphRepository,
    build_wiki_graph_payload,
)


class _Cursor:
    """준비된 Row를 fetchone·fetchall 형태로 반환하는 Cursor 대역."""

    def __init__(self, response: Any) -> None:
        """현재 SQL 실행에 대응하는 응답을 보관한다."""
        self._response = response

    async def fetchone(self) -> Any:
        """준비된 단일 Row 또는 목록의 첫 Row를 반환한다."""
        if isinstance(self._response, list):
            return self._response[0] if self._response else None
        return self._response

    async def fetchall(self) -> list[Any]:
        """준비된 응답을 Row 목록으로 반환한다."""
        if self._response is None:
            return []
        if isinstance(self._response, list):
            return self._response
        return [self._response]


class _Connection:
    """실행된 SQL과 파라미터를 기록하는 비동기 연결 대역."""

    def __init__(self, responses: list[Any]) -> None:
        """실행 순서별 응답과 빈 SQL 기록을 초기화한다."""
        self._responses = list(responses)
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """테스트용 비동기 트랜잭션 문맥을 제공한다."""
        yield

    async def execute(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> _Cursor:
        """SQL을 기록하고 다음 준비 응답의 Cursor를 반환한다."""
        self.executed.append((query, params))
        response = self._responses.pop(0) if self._responses else None
        return _Cursor(response)


class _Pool:
    """하나의 테스트 연결을 비동기 Pool 문맥으로 노출한다."""

    def __init__(self, connection: _Connection) -> None:
        """반환할 연결을 보관한다."""
        self._connection = connection

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_Connection]:
        """저장소가 사용할 테스트 연결을 반환한다."""
        yield self._connection


def _repository(connection: _Connection) -> PostgresWikiGraphRepository:
    """실제 Pool을 열지 않고 테스트 연결이 주입된 저장소를 만든다."""
    repository = object.__new__(PostgresWikiGraphRepository)
    repository._pool = _Pool(connection)  # type: ignore[assignment]
    return repository


def _node(node_id: str, kind: str, title: str) -> dict[str, object]:
    """Graph Payload 조립 테스트용 Wiki 문서 Row를 만든다."""
    return {
        "id": node_id,
        "document_kind": kind,
        "document_key": title.lower(),
        "file_path": f"{kind}s/{title.lower()}.md",
        "subtype": "product" if kind == "entity" else "method",
        "version": 2,
        "updated_at": datetime(2026, 7, 15, tzinfo=UTC),
        "title": title,
        "summary": f"{title} summary",
        "normalized_content": f"# {title}",
        "source_metadata": {"aliases": [f"{title} alias"]},
    }


def test_build_wiki_graph_payload_counts_edges_and_orphans() -> None:
    """Node 차수와 Entity·Concept·고립 Node 집계를 정확히 계산한다."""
    payload = build_wiki_graph_payload(
        user_id="user-1",
        node_rows=[
            _node("entity-1", "entity", "Obsidian"),
            _node("concept-1", "concept", "Linked Notes"),
            _node("concept-2", "concept", "Orphan"),
        ],
        edge_rows=[
            {
                "source_document_id": "entity-1",
                "target_document_id": "concept-1",
                "relation_type": "applies_concept",
                "metadata": {"confidence": 0.9},
            },
            {
                "source_document_id": "missing",
                "target_document_id": "concept-1",
                "relation_type": "applies_concept",
                "metadata": {},
            },
            {
                "source_document_id": "entity-1",
                "target_document_id": "concept-1",
                "relation_type": "associated_with",
                "metadata": {"confidence": 0.8},
            },
        ],
        wiki_version={
            "version": 4,
            "activated_at": datetime(2026, 7, 15, tzinfo=UTC),
        },
    )
    response = WikiGraphResponse.model_validate(payload)

    assert response.wiki_version == 4
    assert response.stats.node_count == 3
    assert response.stats.edge_count == 2
    assert response.stats.entity_count == 1
    assert response.stats.concept_count == 2
    assert response.stats.orphan_count == 1
    assert [node.degree for node in response.nodes] == [1, 1, 0]
    assert response.nodes[0].aliases == ["Obsidian alias"]


def test_get_graph_reads_only_active_non_rejected_relations() -> None:
    """Graph Edge 조회가 활성·비거절 관계와 활성 양끝 노드로 제한되는지 검증한다."""
    connection = _Connection([None, [], [], None])

    payload = asyncio.run(_repository(connection).get_graph("user-1"))

    relation_query = connection.executed[2][0]
    assert payload["stats"]["edge_count"] == 0  # type: ignore[index]
    assert "relation.status = 'active'" in relation_query
    assert "relation.review_status <> 'rejected'" in relation_query
    assert "source.status = 'active'" in relation_query
    assert "target.status = 'active'" in relation_query
    assert "source.deleted_at IS NULL" in relation_query
    assert "target.deleted_at IS NULL" in relation_query


def test_get_document_reads_only_active_non_rejected_relations() -> None:
    """문서 상세의 양방향 관계가 활성·비거절 Head와 활성 이웃만 반환하는지 검증한다."""
    connection = _Connection(
        [
            None,
            {
                "document_id": "doc-1",
                "document_version_id": "version-1",
                "document_kind": "concept",
                "document_key": "weather",
                "file_path": "concepts/weather.md",
                "domain": "topic",
                "title": "날씨",
                "summary": "기상 현상",
                "version": 1,
                "updated_at": datetime(2026, 8, 7, tzinfo=UTC),
                "markdown": "# 날씨",
                "source_metadata": {},
                "source_count": 0,
            },
            [],
            [],
        ]
    )

    document = asyncio.run(_repository(connection).get_document("user-1", "doc-1"))

    relation_query = connection.executed[3][0]
    assert document is not None and document["relations"] == []
    assert "relation.status = 'active'" in relation_query
    assert "relation.review_status <> 'rejected'" in relation_query
    assert "related.status = 'active'" in relation_query
    assert "related.deleted_at IS NULL" in relation_query
