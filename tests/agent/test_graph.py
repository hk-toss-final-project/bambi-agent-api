"""LangGraph 오케스트레이션 그래프의 노드 순서와 결과 조립을 검증한다."""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from agent import graph as agent_graph


class _FakeConnection:
    """transaction 문맥만 제공하는 Connection Test Double."""

    def __init__(self) -> None:
        """Transaction 진입 횟수를 0으로 초기화한다."""
        self.transactions = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """열린 Transaction 수를 세는 문맥을 제공한다."""
        self.transactions += 1
        yield


def _fake_source() -> SimpleNamespace:
    """그래프 노드가 읽는 원본 Version 레코드 대역."""
    return SimpleNamespace(
        source_document_id="source-1",
        source_document_version_id="source-version-1",
        namespace_key="user/user-1",
        title="원본 제목",
        raw_content="# 본문",
        description="설명",
        tags=["tag"],
        canonical_url="https://example.com",
        content_hash="hash",
    )


def _fake_persisted() -> SimpleNamespace:
    """persist 노드가 반환하는 Build 결과 대역."""
    document = SimpleNamespace(
        document_id="doc-1",
        document_version_id="doc-version-1",
        document_kind="entity",
        document_key="entity-key",
        file_path="entities/entity-key.md",
        version=1,
        action="created",
    )
    return SimpleNamespace(
        wiki_version_id="wiki-version-1",
        wiki_version=3,
        chunk_count=2,
        stored_relation_count=4,
        affected_documents=[document],
    )


def test_run_personal_wiki_build_assembles_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wiki 그래프가 조회→분류→계획→저장→임베딩 순서로 결과를 조립한다."""
    order: list[str] = []
    plan = SimpleNamespace(
        index=SimpleNamespace(content="index"),
        source_manifest=SimpleNamespace(content="manifest"),
        log_entry=SimpleNamespace(content="log"),
        extracted_relation_count=2,
        isolated_node_count=1,
        relation_warnings=["관계 경고"],
    )

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """테스트에서 DB 사용자 Scope 설정을 생략한다."""
        return None

    async def fake_get_source(connection: Any, **kwargs: Any) -> SimpleNamespace:
        """원본 조회 순서를 기록하고 고정 원본을 반환한다."""
        order.append("load_source")
        return _fake_source()

    async def fake_entries(connection: Any, **kwargs: Any) -> list[object]:
        """기존 Wiki 문서가 없는 상태를 반환한다."""
        return []

    async def fake_relations(connection: Any, **kwargs: Any) -> list[object]:
        """기존 Wiki 관계가 없는 상태를 반환한다."""
        return []

    def fake_classify(**kwargs: Any) -> str:
        """분류 입력을 검증하고 고정 분류 결과를 반환한다."""
        order.append("classify")
        assert kwargs["source_title"] == "원본 제목"
        assert kwargs["model"] == "test-model"
        return "classification"

    async def fake_wba_003(**kwargs: Any) -> SimpleNamespace:
        """WBA-003 계획 함수 호출을 기록하고 고정 계획을 반환한다."""
        order.append("plan")
        assert kwargs["classification"] == "classification"
        return plan

    async def fake_pwiki_002(
        connection: Any, **kwargs: Any
    ) -> SimpleNamespace:
        """PWIKI-002 facade 호출을 기록하고 저장 결과를 반환한다."""
        order.append("persist")
        assert kwargs["plan"] is plan
        assert kwargs["job_id"] == "job-1"
        return _fake_persisted()

    async def fake_int_011(
        repository: Any, user_id: str, *, limit: int = 20
    ) -> dict[str, Any]:
        """Build 완료 후 재계산 훅 호출을 기록하고 고정 Profile을 반환한다."""
        order.append("recalculate")
        assert user_id == "user-1"
        return {"version": 7}

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        agent_graph, "get_user_source_document_version_for_agent", fake_get_source
    )
    monkeypatch.setattr(agent_graph, "list_existing_wiki_entries", fake_entries)
    monkeypatch.setattr(agent_graph, "list_existing_wiki_relations", fake_relations)
    monkeypatch.setattr(agent_graph, "classify_source_for_wiki", fake_classify)
    monkeypatch.setattr(agent_graph, "wba_003", fake_wba_003)
    monkeypatch.setattr(agent_graph, "pwiki_002", fake_pwiki_002)
    monkeypatch.setattr(agent_graph, "int_011", fake_int_011)

    connection = _FakeConnection()
    result = asyncio.run(
        agent_graph.run_personal_wiki_build(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_version_id="source-version-1",
            job_id="job-1",
            model="test-model",
        )
    )

    assert order == ["load_source", "classify", "plan", "persist", "recalculate"]
    assert result["source_document_id"] == "source-1"
    assert result["wiki_version_id"] == "wiki-version-1"
    assert result["chunk_count"] == 2
    assert result["extracted_relation_count"] == 2
    assert result["stored_relation_count"] == 4
    assert result["isolated_node_count"] == 1
    assert result["relation_warnings"] == ["관계 경고"]
    assert "embedding_count" not in result
    assert result["affected_documents"][0]["document_key"] == "entity-key"
    assert result["artifacts"]["index"] == "index"


def test_run_personal_wiki_build_survives_interest_recalc_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """관심사 재계산 훅이 실패해도 Build 결과 Payload는 그대로 반환된다."""
    plan = SimpleNamespace(
        index=SimpleNamespace(content="index"),
        source_manifest=SimpleNamespace(content="manifest"),
        log_entry=SimpleNamespace(content="log"),
        extracted_relation_count=0,
        isolated_node_count=0,
        relation_warnings=[],
    )

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """테스트에서 DB 사용자 Scope 설정을 생략한다."""
        return None

    async def fake_get_source(connection: Any, **kwargs: Any) -> SimpleNamespace:
        """고정 원본을 반환한다."""
        return _fake_source()

    async def fake_listing(connection: Any, **kwargs: Any) -> list[object]:
        """기존 Wiki 상태가 비어 있는 것으로 반환한다."""
        return []

    async def fake_wba_003(**kwargs: Any) -> SimpleNamespace:
        """고정 Build 계획을 반환한다."""
        return plan

    async def fake_pwiki_002(connection: Any, **kwargs: Any) -> SimpleNamespace:
        """고정 저장 결과를 반환한다."""
        return _fake_persisted()

    async def failing_int_011(
        repository: Any, user_id: str, *, limit: int = 20
    ) -> dict[str, Any]:
        """재계산이 실패하는 상황을 재현한다."""
        raise RuntimeError("재계산 실패")

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        agent_graph, "get_user_source_document_version_for_agent", fake_get_source
    )
    monkeypatch.setattr(agent_graph, "list_existing_wiki_entries", fake_listing)
    monkeypatch.setattr(agent_graph, "list_existing_wiki_relations", fake_listing)
    monkeypatch.setattr(
        agent_graph, "classify_source_for_wiki", lambda **kwargs: "classification"
    )
    monkeypatch.setattr(agent_graph, "wba_003", fake_wba_003)
    monkeypatch.setattr(agent_graph, "pwiki_002", fake_pwiki_002)
    monkeypatch.setattr(agent_graph, "int_011", failing_int_011)

    result = asyncio.run(
        agent_graph.run_personal_wiki_build(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            source_document_version_id="source-version-1",
            job_id="job-1",
            model="test-model",
        )
    )

    assert result["wiki_version_id"] == "wiki-version-1"
    assert result["chunk_count"] == 2


def _disable_research(monkeypatch: pytest.MonkeyPatch) -> None:
    """조사원 에이전트를 끄고 토픽 성격 판정도 고정한다.

    두 함수 모두 실제 LLM·DB를 사용하므로 그래프 테스트에서는 대체한다.
    """
    monkeypatch.setattr(agent_graph, "research_agent_enabled", lambda: False)
    monkeypatch.setattr(agent_graph, "resolve_topic_intent", lambda *args: "news")


def test_run_report_generation_chains_search_generate_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report Builder 그래프가 검색→생성→영속화 순서로 저장 결과를 반환한다."""
    order: list[str] = []

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """테스트에서 DB 사용자 Scope 설정을 생략한다."""
        return None

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[str]:
        """PRAG-003 검색 호출을 기록하고 고정 Context를 반환한다."""
        order.append("load_context")
        assert kwargs["query"] == "개인화"
        return ["context-1"]

    async def fake_prag_006(contexts: list[str]) -> list[str]:
        """검색 Context를 변경 없이 반환한다."""
        return contexts

    def fake_collect_live_context(topic: str, user_id: str, *, model: str = "") -> list:
        """실시간 수집(뉴스·YouTube·Reddit + LLM)을 대체한다.

        대체하지 않으면 이 테스트가 실제 네트워크와 OpenAI를 호출한다.
        """
        order.append("collect_live")
        assert topic == "개인화"
        return []

    def fake_generate(**kwargs: Any) -> str:
        """생성 입력을 검증하고 고정 콘텐츠를 반환한다(품질 루프 래퍼를 대체)."""
        order.append("generate")
        assert kwargs["contexts"] == ["context-1"]
        assert kwargs["language"] == "ko"
        return "generated"

    async def fake_prag_007(connection: Any, **kwargs: Any) -> dict[str, object]:
        """PRAG-007 저장 호출을 기록하고 고정 결과를 반환한다."""
        order.append("persist")
        assert kwargs["generated"] == "generated"
        assert kwargs["attempt_number"] == 2
        assert kwargs["latency_ms"] >= 0
        return {"content_candidate_id": "candidate-1"}

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "prag_003", fake_prag_003)
    monkeypatch.setattr(agent_graph, "prag_006", fake_prag_006)
    monkeypatch.setattr(agent_graph, "generate_report_content_with_quality", fake_generate)
    monkeypatch.setattr(agent_graph, "collect_live_context", fake_collect_live_context)
    monkeypatch.setattr(agent_graph, "prag_007", fake_prag_007)
    # 이 테스트는 조사원을 끈 고정 경로를 검증한다. 끄지 않으면 research 노드가
    # 실제 LLM을 호출한다(테스트는 LLM을 부르지 않아야 한다).
    _disable_research(monkeypatch)

    connection = _FakeConnection()
    result = asyncio.run(
        agent_graph.run_report_generation(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=2,
            topic="개인화",
            content_type="article",
            language="ko",
            model="test-model",
        )
    )

    # 실시간 수집(REPORT-005)이 개인 Wiki 검색과 생성 사이에 들어간다.
    assert order == ["load_context", "collect_live", "generate", "persist"]
    assert result == {"content_candidate_id": "candidate-1"}
    assert connection.transactions == 2


def _patch_generation_tail(
    monkeypatch: pytest.MonkeyPatch, order: list[str]
) -> list[list[Any]]:
    """조사 이후 단계(선별·생성·저장)를 대체하고 생성에 들어간 근거를 모은다."""
    used_contexts: list[list[Any]] = []

    async def fake_prag_006(contexts: list[Any]) -> list[Any]:
        """맥락화 단계를 통과시킨다."""
        return contexts

    def fake_generate(**kwargs: Any) -> str:
        """생성에 들어간 근거를 기록하고 고정 콘텐츠를 반환한다."""
        order.append("generate")
        used_contexts.append(list(kwargs["contexts"]))
        return "generated"

    async def fake_prag_007(connection: Any, **kwargs: Any) -> dict[str, object]:
        """저장 단계를 대체한다."""
        order.append("persist")
        return {"content_candidate_id": "candidate-1"}

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """persist 단계가 부르는 RLS Scope 설정을 생략한다."""

    monkeypatch.setattr(agent_graph, "prag_006", fake_prag_006)
    monkeypatch.setattr(
        agent_graph, "generate_report_content_with_quality", fake_generate
    )
    monkeypatch.setattr(agent_graph, "prag_007", fake_prag_007)
    monkeypatch.setattr(agent_graph, "resolve_topic_intent", lambda *args: "news")
    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    return used_contexts


def _run_generation() -> dict[str, object]:
    """Report Builder 그래프를 고정 입력으로 실행한다."""
    return asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="코스피",
            content_type="article",
            language="ko",
            model="test-model",
        )
    )


def test_research_agent_output_becomes_generation_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """조사원이 모은 자료가 생성 근거로 그대로 전달된다.

    조사원이 자료를 모으면 기존 고정 경로(prag_003 검색·실시간 수집)는
    실행되지 않아야 한다 — 같은 자료를 두 번 모으면 비용이 두 배가 된다.
    """
    order: list[str] = []
    used_contexts = _patch_generation_tail(monkeypatch, order)

    async def fake_research(connection: Any, **kwargs: Any) -> Any:
        """조사원이 문서 두 건을 모은 상황을 재현한다."""
        order.append("research")
        assert kwargs["topic"] == "코스피"
        return SimpleNamespace(
            documents=("doc-1", "doc-2"),
            calls=(),
            notes="두 건을 모았다.",
            stop_reason="final",
        )

    def fail_prag_003(*args: Any, **kwargs: Any) -> None:
        """고정 경로가 실행되면 즉시 실패시킨다."""
        raise AssertionError("조사원이 성공하면 prag_003을 부르면 안 된다.")

    monkeypatch.setattr(agent_graph, "research_agent_enabled", lambda: True)
    monkeypatch.setattr(agent_graph, "research_context", fake_research)
    monkeypatch.setattr(agent_graph, "prag_003", fail_prag_003)

    result = _run_generation()

    assert order == ["research", "generate", "persist"]
    assert used_contexts == [["doc-1", "doc-2"]]
    assert result == {"content_candidate_id": "candidate-1"}


def test_research_failure_falls_back_to_fixed_collection_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """조사원이 실패해도 기존 경로로 리포트 생성을 계속한다."""
    order: list[str] = []
    _patch_generation_tail(monkeypatch, order)

    async def broken_research(connection: Any, **kwargs: Any) -> Any:
        """조사원 실행 중 오류를 재현한다."""
        order.append("research")
        raise RuntimeError("도구 호출 실패")

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[str]:
        """고정 경로의 개인 Wiki 검색을 대체한다."""
        order.append("load_context")
        return ["context-1"]

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """Scope 설정을 생략한다."""

    def fake_collect(topic: str, user_id: str, *, model: str = "") -> list[Any]:
        """실시간 수집을 대체한다."""
        order.append("collect_live")
        return []

    monkeypatch.setattr(agent_graph, "research_agent_enabled", lambda: True)
    monkeypatch.setattr(agent_graph, "research_context", broken_research)
    monkeypatch.setattr(agent_graph, "prag_003", fake_prag_003)
    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "collect_live_context", fake_collect)

    result = _run_generation()

    assert order == ["research", "load_context", "collect_live", "generate", "persist"]
    assert result == {"content_candidate_id": "candidate-1"}


def test_research_node_is_skipped_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """스위치를 끄면 조사원을 아예 호출하지 않는다."""
    order: list[str] = []
    _patch_generation_tail(monkeypatch, order)

    async def fail_research(connection: Any, **kwargs: Any) -> Any:
        """꺼진 상태에서 호출되면 실패시킨다."""
        raise AssertionError("스위치가 꺼지면 조사원을 부르면 안 된다.")

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[str]:
        """고정 경로 검색을 대체한다."""
        order.append("load_context")
        return ["context-1"]

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """Scope 설정을 생략한다."""

    monkeypatch.setattr(agent_graph, "research_agent_enabled", lambda: False)
    monkeypatch.setattr(agent_graph, "research_context", fail_research)
    monkeypatch.setattr(agent_graph, "prag_003", fake_prag_003)
    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "collect_live_context", lambda *a, **k: [])

    result = _run_generation()

    assert order[0] == "load_context"
    assert result == {"content_candidate_id": "candidate-1"}
