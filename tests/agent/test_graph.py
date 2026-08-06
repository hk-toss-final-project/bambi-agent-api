"""LangGraph 오케스트레이션 그래프의 노드 순서와 결과 조립을 검증한다."""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from agent import graph as agent_graph
from agent.report_builder.api import ResearchOutcome


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
        source_type="web_clipping",
        source_metadata={},
        title="원본 제목",
        raw_content="# 본문",
        description="설명",
        tags=["tag"],
        canonical_url="https://example.com",
        content_hash="hash",
    )


def _fake_onboarding_source() -> SimpleNamespace:
    """온보딩 선택 라벨을 담은 합성 원본 Version 레코드 대역."""
    source = _fake_source()
    source.source_type = "onboarding_seed"
    source.source_metadata = {"labels": ["AI·머신러닝", "반도체", "AI·머신러닝"]}
    source.title = "온보딩 관심 주제 시드"
    source.raw_content = "# 온보딩 관심 주제 시드\n\nAI·머신러닝, 반도체"
    return source


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


def test_run_personal_wiki_build_materializes_onboarding_labels_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실제 Worker 그래프도 온보딩 라벨을 결정적으로 Concept로 만든다."""
    captured: dict[str, Any] = {}
    plan = SimpleNamespace(
        index=SimpleNamespace(content="index"),
        source_manifest=SimpleNamespace(content="manifest"),
        log_entry=SimpleNamespace(content="log"),
        extracted_relation_count=0,
        isolated_node_count=2,
        relation_warnings=[],
    )

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """테스트에서 DB 사용자 Scope 설정을 생략한다."""
        return None

    async def fake_get_source(connection: Any, **kwargs: Any) -> SimpleNamespace:
        """온보딩 합성 원본을 반환한다."""
        return _fake_onboarding_source()

    async def fake_listing(connection: Any, **kwargs: Any) -> list[object]:
        """기존 Wiki 상태가 비어 있는 것으로 반환한다."""
        return []

    def fail_if_llm_is_called(**kwargs: Any) -> str:
        """온보딩 시드에서 일반 LLM 분류가 실행되면 실패시킨다."""
        raise AssertionError("온보딩 시드는 LLM 분류기를 호출하면 안 됩니다.")

    async def fake_wba_003(**kwargs: Any) -> SimpleNamespace:
        """결정적 분류 결과와 모델 표식을 기록한다."""
        captured["classification"] = kwargs["classification"]
        captured["model"] = kwargs["model"]
        return plan

    async def fake_pwiki_002(connection: Any, **kwargs: Any) -> SimpleNamespace:
        """고정 저장 결과를 반환한다."""
        return _fake_persisted()

    async def fake_int_011(
        repository: Any, user_id: str, *, limit: int = 20
    ) -> dict[str, Any]:
        """고정 관심사 재계산 결과를 반환한다."""
        return {"version": 1}

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        agent_graph, "get_user_source_document_version_for_agent", fake_get_source
    )
    monkeypatch.setattr(agent_graph, "list_existing_wiki_entries", fake_listing)
    monkeypatch.setattr(agent_graph, "list_existing_wiki_relations", fake_listing)
    monkeypatch.setattr(agent_graph, "classify_source_for_wiki", fail_if_llm_is_called)
    monkeypatch.setattr(agent_graph, "wba_003", fake_wba_003)
    monkeypatch.setattr(agent_graph, "pwiki_002", fake_pwiki_002)
    monkeypatch.setattr(agent_graph, "int_011", fake_int_011)

    result = asyncio.run(
        agent_graph.run_personal_wiki_build(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            source_document_version_id="source-version-1",
            job_id="job-1",
            model="test-model",
        )
    )

    classification = captured["classification"]
    assert [concept.title for concept in classification.concepts] == [
        "AI·머신러닝",
        "반도체",
    ]
    assert captured["model"] == "deterministic:onboarding-seed-v1"
    assert result["wiki_version_id"] == "wiki-version-1"


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


def _disable_critic(monkeypatch: pytest.MonkeyPatch) -> None:
    """검토자 에이전트를 끈다. 켜두면 그래프 테스트가 실제 LLM을 호출한다."""
    monkeypatch.setattr(agent_graph, "critic_enabled", lambda: False)


def _disable_research(monkeypatch: pytest.MonkeyPatch) -> None:
    """조사원·검토자 에이전트를 끄고 토픽 성격 판정도 고정한다.

    셋 다 실제 LLM·DB를 사용하므로 그래프 테스트에서는 대체한다.
    """
    monkeypatch.setattr(agent_graph, "research_agent_enabled", lambda: False)
    monkeypatch.setattr(agent_graph, "resolve_topic_intent", lambda *args: "news")
    _disable_critic(monkeypatch)


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

    def fake_collect_live_context(
        topic: str,
        user_id: str,
        *,
        model: str = "",
        related_keywords: Any = (),
    ) -> list:
        """실시간 수집(뉴스·YouTube·Reddit + LLM)을 대체한다.

        대체하지 않으면 이 테스트가 실제 네트워크와 OpenAI를 호출한다.
        """
        order.append("collect_live")
        assert topic == "개인화"
        # 조회한 Wiki 이웃 키워드가 수집까지 전달되는지 확인한다.
        assert list(related_keywords) == ["추천 시스템"]
        return []

    async def fake_related_keywords(connection: Any, **kwargs: Any) -> list:
        """Wiki 그래프 이웃 조회를 고정 결과로 대체한다."""
        order.append("related_keywords")
        assert kwargs["topic"] == "개인화"
        return [SimpleNamespace(title="추천 시스템", weight=2.0)]

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
    monkeypatch.setattr(
        agent_graph, "list_related_wiki_keywords", fake_related_keywords
    )
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

    # 실시간 수집(REPORT-005)이 개인 Wiki 검색과 생성 사이에 들어가고, 그 앞에서
    # 확장에 쓸 Wiki 이웃 키워드를 읽는다.
    assert order == [
        "load_context",
        "related_keywords",
        "collect_live",
        "generate",
        "persist",
    ]
    assert result == {"content_candidate_id": "candidate-1"}
    # 이웃 조회는 개인 Wiki 검색과 Transaction을 분리한다(실패 격리).
    assert connection.transactions == 3


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
    _disable_critic(monkeypatch)
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
            collected_live=False,
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

    def fake_collect(
        topic: str,
        user_id: str,
        *,
        model: str = "",
        related_keywords: Any = (),
    ) -> list[Any]:
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


def _patch_for_review(
    monkeypatch: pytest.MonkeyPatch, order: list[str]
) -> list[str]:
    """검토 루프 테스트용으로 조사·생성·저장을 대체하고 교정 지시를 모은다."""
    corrections: list[str] = []

    async def fake_research(connection: Any, **kwargs: Any) -> Any:
        """근거 한 건을 모은 조사 결과를 돌려준다."""
        return SimpleNamespace(
            documents=("doc-1",),
            calls=(),
            collected_live=False,
            notes="",
            stop_reason="final",
        )

    async def fake_prag_006(contexts: list[Any]) -> list[Any]:
        """맥락화 단계를 통과시킨다."""
        return contexts

    def fake_generate(**kwargs: Any) -> str:
        """생성 호출을 세고 전달받은 교정 지시를 기록한다."""
        order.append("generate")
        corrections.append(str(kwargs.get("correction") or ""))
        return "generated"

    async def fake_prag_007(connection: Any, **kwargs: Any) -> dict[str, object]:
        """저장 단계를 대체한다."""
        order.append("persist")
        return {"content_candidate_id": "candidate-1"}

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """Scope 설정을 생략한다."""

    monkeypatch.setattr(agent_graph, "research_agent_enabled", lambda: True)
    monkeypatch.setattr(agent_graph, "research_context", fake_research)
    monkeypatch.setattr(agent_graph, "resolve_topic_intent", lambda *args: "news")
    monkeypatch.setattr(agent_graph, "prag_006", fake_prag_006)
    monkeypatch.setattr(
        agent_graph, "generate_report_content_with_quality", fake_generate
    )
    monkeypatch.setattr(agent_graph, "prag_007", fake_prag_007)
    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "critic_enabled", lambda: True)
    return corrections


def test_critic_revision_sends_the_draft_back_to_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """검토자가 문제를 찾으면 교정 지시와 함께 다시 쓰게 한다."""
    order: list[str] = []
    corrections = _patch_for_review(monkeypatch, order)
    reviews: list[int] = []

    async def fake_review(connection: Any, **kwargs: Any) -> Any:
        """1회차는 재작성 요구, 2회차는 통과."""
        order.append("review")
        reviews.append(1)
        if len(reviews) == 1:
            return SimpleNamespace(
                outcome="revise",
                should_regenerate=True,
                problem="당일 급락이 빠졌다",
                correction="급락 폭을 본문에 넣으세요",
                calls=(),
            )
        return SimpleNamespace(
            outcome="pass",
            should_regenerate=False,
            problem="",
            correction="",
            calls=(),
        )

    monkeypatch.setattr(agent_graph, "review_report", fake_review)

    result = _run_generation()

    assert order == ["generate", "review", "generate", "review", "persist"]
    assert corrections == ["", "급락 폭을 본문에 넣으세요"]
    assert result == {"content_candidate_id": "candidate-1"}


def test_critic_revision_is_capped_at_one_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """검토자가 계속 흠을 잡아도 재작성은 한 번만 한다.

    상한이 없으면 리포트 하나에 LLM 호출이 무한히 늘어난다.
    """
    order: list[str] = []
    _patch_for_review(monkeypatch, order)

    async def always_revise(connection: Any, **kwargs: Any) -> Any:
        """항상 재작성을 요구한다."""
        order.append("review")
        return SimpleNamespace(
            outcome="revise",
            should_regenerate=True,
            problem="아직 부족하다",
            correction="더 고치세요",
            calls=(),
        )

    monkeypatch.setattr(agent_graph, "review_report", always_revise)

    result = _run_generation()

    assert order == ["generate", "review", "generate", "review", "persist"]
    assert result == {"content_candidate_id": "candidate-1"}


def test_critic_failure_does_not_block_publishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """검토가 불가능해도 초안을 그대로 발행한다."""
    order: list[str] = []
    _patch_for_review(monkeypatch, order)

    async def unavailable(connection: Any, **kwargs: Any) -> Any:
        """검토 불가 판정을 돌려준다."""
        order.append("review")
        return SimpleNamespace(
            outcome="unavailable",
            should_regenerate=False,
            problem="",
            correction="",
            calls=(),
        )

    monkeypatch.setattr(agent_graph, "review_report", unavailable)

    result = _run_generation()

    assert order == ["generate", "review", "persist"]
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


def test_legacy_path_skips_live_collection_when_researcher_already_tried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """조사원이 실시간 수집을 이미 시도했으면 고정 경로가 다시 부르지 않는다.

    조사원이 빈손으로 돌아오면 고정 경로로 넘어오는데, 같은 주제로 같은 수집을
    한 번 더 돌리면 지연과 외부 API 호출이 두 배가 된다.
    """
    order: list[str] = []
    _patch_generation_tail(monkeypatch, order)

    async def empty_research(connection: Any, **kwargs: Any) -> Any:
        """수집까지 시도했지만 한 건도 못 모은 조사원을 재현한다."""
        order.append("research")
        return ResearchOutcome(documents=(), collected_live=True)

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[str]:
        """고정 경로의 개인 Wiki 검색을 대체한다."""
        order.append("load_context")
        return ["context-1"]

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """Scope 설정을 생략한다."""

    def fake_collect(
        topic: str,
        user_id: str,
        *,
        model: str = "",
        related_keywords: Any = (),
    ) -> list[Any]:
        """호출되면 안 되는 실시간 수집."""
        order.append("collect_live")
        return []

    monkeypatch.setattr(agent_graph, "research_agent_enabled", lambda: True)
    monkeypatch.setattr(agent_graph, "research_context", empty_research)
    monkeypatch.setattr(agent_graph, "prag_003", fake_prag_003)
    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "collect_live_context", fake_collect)

    result = _run_generation()

    assert order == ["research", "load_context", "generate", "persist"]
    assert "collect_live" not in order
    assert result == {"content_candidate_id": "candidate-1"}


def test_multi_topic_report_gathers_evidence_per_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """주제를 여러 개 주면 주제마다 검색을 따로 돌리고 근거를 합쳐 한 번 생성한다.

    한 번에 합쳐 검색하면 서로 무관한 주제가 섞여 어느 쪽도 제대로 못 찾는다.
    생성은 한 번만 해야 카드도 한 장이 된다.
    """
    searched: list[str] = []
    generated_with: dict[str, Any] = {}

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """DB 사용자 Scope 설정을 생략한다."""
        return None

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[str]:
        """검색어를 기록하고 주제마다 다른 Context를 반환한다."""
        query = kwargs["query"]
        searched.append(query)
        return [f"context-{query}"]

    async def fake_prag_006(contexts: list[str]) -> list[str]:
        """검색 Context를 변경 없이 반환한다."""
        return contexts

    def fake_generate(**kwargs: Any) -> str:
        """생성 입력을 붙잡아 두고 고정 콘텐츠를 반환한다."""
        generated_with.update(kwargs)
        return "generated"

    async def fake_prag_007(connection: Any, **kwargs: Any) -> dict[str, object]:
        """저장 호출을 고정 결과로 대체한다."""
        return {"content_candidate_id": "candidate-1"}

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "prag_003", fake_prag_003)
    monkeypatch.setattr(agent_graph, "prag_006", fake_prag_006)
    monkeypatch.setattr(agent_graph, "generate_report_content_with_quality", fake_generate)
    monkeypatch.setattr(agent_graph, "prag_007", fake_prag_007)
    _disable_research(monkeypatch)

    result = asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="오늘의 관심사 요약",
            topics=["반도체", "프로야구"],
            content_type="interest_news_card",
            language="ko",
            model="test-model",
        )
    )

    # 주제마다 검색이 한 번씩. 카드 제목(topic)으로는 검색하지 않는다.
    assert searched == ["반도체", "프로야구"]
    # 생성은 한 번, 주제 목록을 그대로 받는다.
    assert generated_with["topics"] == ["반도체", "프로야구"]
    assert generated_with["topic"] == "오늘의 관심사 요약"
    # 두 주제의 근거가 모두 들어간다.
    assert generated_with["contexts"] == ["context-반도체", "context-프로야구"]
    assert result == {"content_candidate_id": "candidate-1"}


def test_single_topic_report_keeps_the_existing_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """topics를 주지 않으면 topic 하나로 검색하는 기존 경로 그대로다."""
    searched: list[str] = []

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """DB 사용자 Scope 설정을 생략한다."""
        return None

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[str]:
        """검색어를 기록한다."""
        searched.append(kwargs["query"])
        return ["context-1"]

    async def fake_prag_006(contexts: list[str]) -> list[str]:
        """검색 Context를 변경 없이 반환한다."""
        return contexts

    def fake_collect_live_context(
        topic: str,
        user_id: str,
        *,
        model: str = "",
        related_keywords: Any = (),
    ) -> list:
        """실시간 수집을 대체한다."""
        return []

    def fake_generate(**kwargs: Any) -> str:
        """고정 콘텐츠를 반환한다."""
        return "generated"

    async def fake_prag_007(connection: Any, **kwargs: Any) -> dict[str, object]:
        """저장 호출을 고정 결과로 대체한다."""
        return {"content_candidate_id": "candidate-1"}

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "prag_003", fake_prag_003)
    monkeypatch.setattr(agent_graph, "prag_006", fake_prag_006)
    monkeypatch.setattr(agent_graph, "collect_live_context", fake_collect_live_context)
    monkeypatch.setattr(agent_graph, "generate_report_content_with_quality", fake_generate)
    monkeypatch.setattr(agent_graph, "prag_007", fake_prag_007)
    _disable_research(monkeypatch)

    asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="반도체",
            content_type="interest_news_card",
            language="ko",
            model="test-model",
        )
    )

    assert searched == ["반도체"]
