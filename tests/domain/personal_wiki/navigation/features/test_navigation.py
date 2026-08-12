"""LLM Wiki Navigator의 Locate·Read·Traverse·Packet 계약을 검증한다."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from hashlib import sha256
from types import SimpleNamespace
from typing import Any

import pytest

from domain.personal_wiki.navigation.features import locate, packet, read, traversal
from shared.wiki_navigation_models import (
    WikiNavigationCandidate,
    WikiNavigationPage,
    WikiNavigationTraversal,
)


class _Connection:
    """Navigator가 같은 Connection의 짧은 Transaction을 쓰는지 기록한다."""

    def __init__(self) -> None:
        """Transaction 진입 횟수를 초기화한다."""
        self.transactions = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """중첩 Transaction을 허용하는 비동기 Context를 제공한다."""
        self.transactions += 1
        yield


def _candidate_row(index: int, *, exact: bool = False) -> dict[str, object]:
    """Locate 테스트용 Wiki Page 후보 Row를 만든다."""
    title = "삼성전자" if exact else f"후보-{index:02d}"
    return {
        "document_id": f"document-{index}",
        "document_version_id": f"version-{index}",
        "document_kind": "entity",
        "document_key": f"key-{index}",
        "file_path": f"entities/key-{index}.md",
        "title": title,
        "aliases": [],
        "summary": f"{title} 요약",
        "updated_at": datetime(2026, 8, 10, tzinfo=UTC),
        "exact_match": exact,
        "alias_match": False,
    }


def test_locate_returns_thirty_candidates_without_degree_cutoff(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """후보 30개를 반환하고 뒤쪽 exact 후보를 구조 점수 없이 보존한다."""
    connection = _Connection()
    captured: dict[str, object] = {}
    scoped: list[object] = []
    keyword_rows = [_candidate_row(index) for index in range(29)]
    keyword_rows.append(_candidate_row(29, exact=True))

    async def fake_scope(conn, *, user_id):  # type: ignore[no-untyped-def]
        """Scope가 전달받은 Connection에 적용됐는지 기록한다."""
        scoped.append((conn, user_id))

    async def fake_keyword(conn, **kwargs):  # type: ignore[no-untyped-def]
        """30개 Keyword 후보와 호출 상한을 반환한다."""
        captured.update(kwargs)
        assert conn is connection
        return keyword_rows

    monkeypatch.setattr(locate, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        locate, "load_wiki_navigation_keyword_candidates", fake_keyword
    )

    result = asyncio.run(
        locate.wnav_001(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            query="삼성전자",
        )
    )

    assert len(result) == 30
    assert result[0].title == "삼성전자"
    assert result[0].keyword_rank == 30
    assert captured["limit"] == 30
    assert scoped == [(connection, "user-1")]
    assert connection.transactions == 1
    assert not hasattr(result[0], "degree")


def test_locate_falls_back_to_keyword_when_vector_query_fails(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Vector 조회 장애가 Keyword 후보 반환을 막지 않는다."""
    connection = _Connection()

    async def fake_scope(*args, **kwargs):  # type: ignore[no-untyped-def]
        """RLS Scope 설정을 대체한다."""

    async def fake_keyword(*args, **kwargs):  # type: ignore[no-untyped-def]
        """Keyword 후보 하나를 반환한다."""
        return [_candidate_row(1)]

    async def fail_vector(*args, **kwargs):  # type: ignore[no-untyped-def]
        """Vector 저장소 장애를 재현한다."""
        raise RuntimeError("vector unavailable")

    monkeypatch.setattr(locate, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        locate, "load_wiki_navigation_keyword_candidates", fake_keyword
    )
    monkeypatch.setattr(
        locate, "load_wiki_navigation_vector_candidates", fail_vector
    )

    result = asyncio.run(
        locate.wnav_001(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            query="후보",
            query_embedding=[0.1] * 1536,
        )
    )

    assert [item.title for item in result] == ["후보-01"]
    assert result[0].vector_rank is None
    assert connection.transactions == 2


def test_locate_preserves_keyword_and_vector_score_components(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """RRF 후보가 후속 Consumer 판정에 원래 Keyword·Vector 점수를 함께 전달한다."""
    connection = _Connection()
    keyword = _candidate_row(1)
    keyword["text_score"] = 0.7
    vector = _candidate_row(1)
    vector["vector_score"] = 0.82

    async def fake_scope(*args, **kwargs):  # type: ignore[no-untyped-def]
        """RLS Scope 설정을 대체한다."""

    async def fake_keyword(*args, **kwargs):  # type: ignore[no-untyped-def]
        """Keyword 구성 점수가 있는 후보를 반환한다."""
        return [keyword]

    async def fake_vector(*args, **kwargs):  # type: ignore[no-untyped-def]
        """같은 후보의 Vector 유사도 점수를 반환한다."""
        return [vector]

    monkeypatch.setattr(locate, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(locate, "load_wiki_navigation_keyword_candidates", fake_keyword)
    monkeypatch.setattr(locate, "load_wiki_navigation_vector_candidates", fake_vector)

    result = asyncio.run(
        locate.wnav_001(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            query="후보",
            query_embedding=[0.1] * 1536,
        )
    )

    assert result[0].keyword_score == 0.7
    assert result[0].vector_score == 0.82


def test_read_preserves_page_version_and_source_interest_times(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Page Version과 Source 저장·관심 시각을 응답에 보존한다."""
    connection = _Connection()
    saved_at = datetime(2026, 8, 9, 10, tzinfo=UTC)
    stored_at = datetime(2026, 8, 9, 10, 0, 3, tzinfo=UTC)
    scoped: list[object] = []

    async def fake_scope(conn, *, user_id):  # type: ignore[no-untyped-def]
        """두 Read가 같은 Connection에 Scope를 설정했는지 기록한다."""
        scoped.append((conn, user_id))

    async def fake_pages(conn, **kwargs):  # type: ignore[no-untyped-def]
        """고정 Version의 Page와 Chunk Row를 반환한다."""
        assert kwargs["document_version_ids"] == ["version-1"]
        return [
            {
                "document_id": "document-1",
                "document_version_id": "version-1",
                "document_kind": "concept",
                "document_key": "local-llm",
                "file_path": "concepts/local-llm.md",
                "title": "로컬 LLM",
                "aliases": ["Local LLM"],
                "summary": "로컬 실행 관심",
                "markdown": "## Definition\n본문",
                "version": 2,
                "updated_at": stored_at,
                "role": "seed",
                "chunk_id": "chunk-1",
                "chunk_index": 0,
                "chunk_content": "본문",
                "chunk_metadata": {"heading_path": ["Definition"]},
            }
        ]

    async def fake_sources(conn, **kwargs):  # type: ignore[no-untyped-def]
        """사용자 행동과 DB 저장 시각이 다른 Source를 반환한다."""
        return [
            {
                "wiki_document_version_id": "version-1",
                "source_document_id": "source-1",
                "source_document_version_id": "source-version-1",
                "source_type": "web_clipping",
                "title": "로컬 LLM 기사",
                "url": "https://example.com/local-llm",
                "relation_type": "source",
                "saved_at": saved_at,
                "saved_at_source": "event_occurred_at",
                "stored_at": stored_at,
                "published_at": datetime(2026, 8, 8, tzinfo=UTC),
                "clipped_on": date(2026, 8, 9),
            }
        ]

    monkeypatch.setattr(read, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(read, "load_wiki_navigation_pages", fake_pages)
    monkeypatch.setattr(read, "load_wiki_navigation_sources", fake_sources)

    pages = asyncio.run(
        read.wnav_002(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            document_version_ids=["version-1"],
        )
    )
    sources = asyncio.run(
        read.wnav_004(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            wiki_document_version_ids=["version-1"],
        )
    )

    assert pages[0].document_version_id == "version-1"
    assert pages[0].excerpts[0].heading_path == ("Definition",)
    assert sources[0].saved_at == saved_at
    assert sources[0].stored_at == stored_at
    assert sources[0].saved_at_source == "event_occurred_at"
    assert scoped == [(connection, "user-1"), (connection, "user-1")]


def test_traverse_applies_confidence_gate_and_stops_cycles(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """저신뢰 관계를 제외하고 Cycle 없이 최대 2홉을 순회한다."""
    connection = _Connection()
    calls: list[tuple[str, ...]] = []

    async def fake_scope(*args, **kwargs):  # type: ignore[no-untyped-def]
        """RLS Scope 설정을 대체한다."""

    async def fake_relations(conn, *, document_ids, **kwargs):  # type: ignore[no-untyped-def]
        """A→B→C와 C→A Cycle, 저신뢰 A→X 관계를 반환한다."""
        calls.append(tuple(document_ids))
        common = {
            "review_status": "accepted",
            "provenance_kind": "source_explicit",
            "confidence": 0.9,
            "rationale": "근거 있음",
            "supports": [
                {
                    "source_document_version_id": "source-version-1",
                    "provenance_kind": "source_explicit",
                    "confidence": 0.9,
                    "review_status": "accepted",
                    "evidence": "원문 근거",
                    "rationale": "명시 관계",
                }
            ],
        }
        if document_ids == ["A"]:
            return [
                {
                    **common,
                    "relation_id": "r-ab",
                    "source_document_id": "A",
                    "target_document_id": "B",
                    "relation_type": "associated_with",
                },
                {
                    **common,
                    "relation_id": "r-ax",
                    "source_document_id": "A",
                    "target_document_id": "X",
                    "relation_type": "associated_with",
                    "confidence": 0.2,
                },
            ]
        return [
            {
                **common,
                "relation_id": "r-bc",
                "source_document_id": "B",
                "target_document_id": "C",
                "relation_type": "part_of",
            },
            {
                **common,
                "relation_id": "r-ba",
                "source_document_id": "B",
                "target_document_id": "A",
                "relation_type": "associated_with",
            },
        ]

    monkeypatch.setattr(traversal, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        traversal, "load_wiki_navigation_relations", fake_relations
    )

    result = asyncio.run(
        traversal.wnav_003(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            seed_document_ids=["A"],
            max_depth=2,
            max_pages=3,
        )
    )

    assert result.document_ids == ("A", "B", "C")
    assert [item.relation_id for item in result.relations] == [
        "r-ab",
        "r-bc",
        "r-ba",
    ]
    assert all(item.target_document_id != "X" for item in result.relations)
    assert calls == [("A",), ("B",)]


def test_traverse_applies_depth_quotas_and_carries_unused_seed_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """빈 Seed 몫을 1홉으로 넘기고 2홉까지 전체 6 Page 상한을 지킨다."""
    connection = _Connection()
    calls: list[tuple[str, ...]] = []
    common = {
        "review_status": "accepted",
        "provenance_kind": "source_explicit",
        "rationale": "근거 있음",
        "supports": [
            {
                "source_document_version_id": "source-version-1",
                "provenance_kind": "source_explicit",
                "confidence": 0.95,
                "review_status": "accepted",
                "evidence": "원문 근거",
                "rationale": "명시 관계",
            }
        ],
    }

    def relation(source: str, target: str, confidence: float) -> dict[str, object]:
        """신뢰도 순위 검증용 관계 Row를 만든다."""
        return {
            **common,
            "relation_id": f"r-{source.lower()}{target.lower()}",
            "source_document_id": source,
            "target_document_id": target,
            "relation_type": "associated_with",
            "confidence": confidence,
        }

    async def fake_scope(*args: Any, **kwargs: Any) -> None:
        """RLS Scope 설정을 대체한다."""

    async def fake_relations(
        conn: object, *, document_ids: list[str], **kwargs: Any
    ) -> list[dict[str, object]]:
        """각 깊이에 Page 예산보다 하나 많은 후보를 반환한다."""
        calls.append(tuple(document_ids))
        if document_ids == ["A"]:
            return [
                relation("A", "B", 0.95),
                relation("A", "C", 0.94),
                relation("A", "D", 0.93),
                relation("A", "X", 0.92),
            ]
        return [
            relation("B", "E", 0.95),
            relation("C", "F", 0.94),
            relation("D", "G", 0.93),
        ]

    monkeypatch.setattr(traversal, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        traversal, "load_wiki_navigation_relations", fake_relations
    )

    result = asyncio.run(
        traversal.wnav_003(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            seed_document_ids=["A"],
            max_depth=2,
            max_pages=6,
            seed_page_limit=2,
            hop_page_limits=(2, 2),
        )
    )

    assert result.document_ids == ("A", "B", "C", "D", "E", "F")
    assert result.document_hops == (
        ("A", 0),
        ("B", 1),
        ("C", 1),
        ("D", 1),
        ("E", 2),
        ("F", 2),
    )
    assert [item.relation_id for item in result.relations] == [
        "r-ab",
        "r-ac",
        "r-ad",
        "r-be",
        "r-cf",
    ]
    assert result.truncated is True
    assert calls == [("A",), ("B", "C", "D")]


def test_packet_contains_context_without_answer_field() -> None:
    """Context Packet이 후보·Trace를 담되 최종 답변 필드를 만들지 않는다."""
    candidate = WikiNavigationCandidate(
        document_id="document-1",
        document_version_id="version-1",
        document_kind="concept",
        document_key="local-llm",
        file_path="concepts/local-llm.md",
        title="로컬 LLM",
        aliases=(),
        summary="요약",
        updated_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    result = asyncio.run(
        packet.wnav_005(
            query="로컬 LLM",
            wiki_version_id="wiki-version-1",
            candidates=[candidate],
            pages=[],
            relations=[],
            sources=[],
        )
    )

    assert result.candidates == (candidate,)
    assert result.trace[0].step == "locate"
    assert not hasattr(result, "answer")


def test_packet_pins_budget_limits_seeds_and_records_page_hops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2-hop Packet이 Seed 2개 상한과 Page별 실제 깊이를 보존한다."""
    now = datetime(2026, 8, 12, tzinfo=UTC)

    def page_model(
        document_id: str, version_id: str, *, role: str
    ) -> WikiNavigationPage:
        """Packet 조립 검증용 최소 Wiki Page를 만든다."""
        return WikiNavigationPage(
            document_id=document_id,
            document_version_id=version_id,
            document_kind="concept",
            document_key=document_id,
            file_path=f"concepts/{document_id}.md",
            title=document_id,
            aliases=(),
            summary=f"{document_id} 요약",
            markdown=f"{document_id} 본문",
            version=1,
            updated_at=now,
            role=role,
        )

    seed_pages = [
        page_model("doc-a", "version-a", role="seed"),
        page_model("doc-b", "version-b", role="seed"),
    ]
    traversed_page = page_model("doc-c", "version-c", role="traversed")
    read_calls: list[list[str]] = []

    async def fake_pages(*args: Any, **kwargs: Any) -> list[WikiNavigationPage]:
        """초기 Seed와 순회 완료 Page 읽기를 순서대로 반환한다."""
        read_calls.append(list(kwargs["document_version_ids"]))
        return seed_pages if len(read_calls) == 1 else [*seed_pages, traversed_page]

    async def fake_traversal(*args: Any, **kwargs: Any) -> WikiNavigationTraversal:
        """Seed에서 1홉 Page 하나를 찾은 결과를 반환한다."""
        assert kwargs["seed_page_limit"] == 2
        assert kwargs["hop_page_limits"] == (2, 2)
        return WikiNavigationTraversal(
            document_ids=("doc-a", "doc-b", "doc-c"),
            relations=(),
            document_hops=(("doc-a", 0), ("doc-b", 0), ("doc-c", 1)),
        )

    async def fake_sources(*args: Any, **kwargs: Any) -> list[Any]:
        """Source 조회를 비운다."""
        return []

    monkeypatch.setattr(packet, "wnav_002", fake_pages)
    monkeypatch.setattr(packet, "wnav_003", fake_traversal)
    monkeypatch.setattr(packet, "wnav_004", fake_sources)

    result = asyncio.run(
        packet.wnav_006(
            _Connection(),  # type: ignore[arg-type]
            user_id="user-1",
            query="AI 에이전트",
            selected_document_version_ids=[
                "version-a",
                "version-b",
                "version-dropped",
            ],
            max_depth=2,
            max_seed_pages=2,
            max_pages=6,
            max_chunks=12,
            hop_page_limits=(2, 2),
        )
    )

    assert read_calls == [
        ["version-a", "version-b"],
        ["version-a", "version-b"],
    ]
    assert [page.hops for page in result.pages] == [0, 0, 1]
    assert result.budget.to_payload() == {
        "max_depth": 2,
        "max_seed_pages": 2,
        "max_pages": 6,
        "max_chunks": 12,
        "hop_page_limits": [2, 2],
    }
    assert result.truncated is True


def test_navigation_relation_failure_emits_countable_log(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """관계 폴백을 집계 가능한 이벤트로 남기고 원문 Query는 숨긴다."""
    page = SimpleNamespace(
        document_id="seed-document",
        document_version_id="seed-version",
    )

    async def fake_pages(*args: Any, **kwargs: Any) -> list[Any]:
        """Seed Page 읽기와 폴백 후 재읽기에 같은 Page를 반환한다."""
        return [page]

    async def fail_traversal(*args: Any, **kwargs: Any) -> Any:
        """관계 저장소 장애를 재현한다."""
        raise RuntimeError("relation database unavailable")

    async def fake_sources(*args: Any, **kwargs: Any) -> list[Any]:
        """관계 폴백 로그 검증에서 Source 조회를 비운다."""
        return []

    monkeypatch.setattr(packet, "wnav_002", fake_pages)
    monkeypatch.setattr(packet, "wnav_003", fail_traversal)
    monkeypatch.setattr(packet, "wnav_004", fake_sources)
    raw_query = "사용자 원문 검색어"

    with caplog.at_level(logging.WARNING, logger=packet.logger.name):
        result = asyncio.run(
            packet.wnav_006(
                _Connection(),  # type: ignore[arg-type]
                user_id="user-77",
                query=raw_query,
                selected_document_version_ids=["seed-version"],
                max_depth=1,
                max_pages=6,
            )
        )

    assert result.fallback_reason == "relation_traversal_failed"
    event = caplog.messages[-1]
    assert "event=wiki_navigation_relation_traversal_failed" in event
    assert f"query_hash={sha256(raw_query.encode('utf-8')).hexdigest()[:16]}" in event
    assert "seed_page_count=1" in event
    assert "error_type=RuntimeError" in event
    assert raw_query not in event
