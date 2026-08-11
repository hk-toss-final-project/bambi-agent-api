"""LangGraph 오케스트레이션 그래프의 노드 순서와 결과 조립을 검증한다."""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from agent import graph as agent_graph
from agent.report_builder.api import ResearchOutcome
from infrastructure.persistence.api import WikiGraphRelationSnapshot
from shared.report_models import ReportContextDocument
from shared.wiki_models import WikiClassification


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


def test_changed_onboarding_seed_runs_full_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """두 번째 온보딩 Version은 이전 시드 전용 노드를 제거하도록 전체 재구성한다."""
    source = _fake_onboarding_source()
    source.version = 2
    source.head_current_version = 2
    rebuilt = SimpleNamespace(
        persisted=_fake_persisted(),
        source_count=3,
        superseded_document_count=2,
        embedding_count=1,
        quality=SimpleNamespace(metrics={"error_count": 0}, issues=[]),
    )
    calls: list[str] = []

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """테스트에서 DB Scope 설정을 생략한다."""
        return None

    async def fake_source(connection: Any, **kwargs: Any) -> SimpleNamespace:
        """현재 Head가 두 번째 Version인 온보딩 원본을 반환한다."""
        return source

    async def fake_rebuild(connection: Any, **kwargs: Any) -> SimpleNamespace:
        """Full Rebuild 호출과 Job 인자를 기록한다."""
        calls.append("rebuild")
        assert kwargs["job_id"] == "job-2"
        return rebuilt

    async def fake_recalculate(connection: Any, *, user_id: str) -> None:
        """관심사 재계산 후속 훅을 기록한다."""
        calls.append("recalculate")

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        agent_graph, "get_user_source_document_version_for_agent", fake_source
    )
    monkeypatch.setattr(agent_graph, "rebuild_full_wiki", fake_rebuild)
    monkeypatch.setattr(agent_graph, "_recalculate_interest_profile", fake_recalculate)

    result = asyncio.run(
        agent_graph.run_personal_wiki_build(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            source_document_version_id="source-version-2",
            job_id="job-2",
        )
    )

    assert calls == ["rebuild", "recalculate"]
    assert result["full_rebuild"] is True
    assert result["superseded_document_count"] == 2


def test_run_personal_wiki_rebuild_retires_wiki_when_no_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """마지막 활성 원본 해제는 빈 Wiki 상태와 관심사 retire를 결과에 반영한다."""
    calls: list[str] = []

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """테스트 DB Scope 설정을 생략한다."""
        calls.append("scope")

    async def fake_sources(connection: Any, *, user_id: str) -> list[Any]:
        """활성 원본이 없는 상태를 반환한다."""
        return []

    async def fake_retire(connection: Any, **kwargs: Any) -> dict[str, int]:
        """기존 Wiki 파생물 비활성화 결과를 반환한다."""
        calls.append("retire")
        return {"superseded_document_count": 3, "unsearchable_chunk_count": 7}

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        agent_graph, "list_user_source_versions_for_rebuild", fake_sources
    )
    monkeypatch.setattr(
        agent_graph, "retire_personal_wiki_without_sources", fake_retire
    )

    result = asyncio.run(
        agent_graph.run_personal_wiki_rebuild(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="rebuild-job-1",
        )
    )

    assert calls == ["scope", "scope", "retire"]
    assert result["full_rebuild"] is True
    assert result["source_count"] == 0
    assert result["superseded_document_count"] == 3


def _graph_snapshot_relation(
    source_key: str,
    source_title: str,
    target_key: str,
    target_title: str,
    **overrides: object,
) -> WikiGraphRelationSnapshot:
    """기본 검증 상태의 Wiki Graph 관계 Snapshot 한 건을 만든다."""
    values: dict[str, object] = {
        "source_document_kind": "concept",
        "source_document_key": source_key,
        "source_title": source_title,
        "source_domain": "topic",
        "target_document_kind": "concept",
        "target_document_key": target_key,
        "target_title": target_title,
        "target_domain": "topic",
        "relation_type": "associated_with",
        "status": "active",
        "review_status": "accepted",
        "provenance_kind": "source_explicit",
        "confidence": 0.9,
        "weight": 1.0,
        "supported": True,
    }
    values.update(overrides)
    return WikiGraphRelationSnapshot(**values)  # type: ignore[arg-type]


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
    """Wiki 그래프가 분류→identity 판정→품질 검증→저장 순서로 결과를 조립한다."""
    order: list[str] = []
    plan = SimpleNamespace(
        entities=[],
        concepts=[],
        relations=[],
        node_dispositions=[],
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

    classification = WikiClassification()
    resolved_classification = WikiClassification(source_summary="resolved")

    def fake_classify(**kwargs: Any) -> WikiClassification:
        """분류 입력을 검증하고 고정 분류 결과를 반환한다."""
        order.append("classify")
        assert kwargs["source_title"] == "원본 제목"
        assert kwargs["model"] == "test-model"
        return classification

    def fake_prepare_identity(**kwargs: Any) -> SimpleNamespace:
        """LLM 판정이 필요한 identity 충돌 한 건을 반환한다."""
        order.append("prepare_identity")
        assert kwargs["classification"] is classification
        return SimpleNamespace(classification=classification, conflicts=("conflict",))

    def fake_resolve_identity(**kwargs: Any) -> SimpleNamespace:
        """identity 충돌을 해결한 고정 분류 결과를 반환한다."""
        order.append("resolve_identity")
        assert kwargs["source_title"] == "원본 제목"
        return SimpleNamespace(
            classification=resolved_classification,
            model="test-resolver",
            resolved_conflict_count=1,
            input_tokens=120,
            output_tokens=30,
        )

    def fake_quality_gate(**kwargs: Any) -> WikiClassification:
        """저장 전 품질 검증 호출을 기록하고 분류 결과를 통과시킨다."""
        order.append("quality_gate")
        assert kwargs["classification"] is resolved_classification
        return kwargs["classification"]

    async def fake_wba_003(**kwargs: Any) -> SimpleNamespace:
        """WBA-003 계획 함수 호출을 기록하고 고정 계획을 반환한다."""
        order.append("plan")
        assert kwargs["classification"] is resolved_classification
        assert kwargs["model"] == (
            "test-model;identity=test-resolver;relation=test-model"
        )
        return plan

    async def fake_plan_quality(*args: Any, **kwargs: Any) -> SimpleNamespace:
        """계획 Lint 순서를 기록하고 통과 보고서를 반환한다."""
        order.append("validate_plan")
        return SimpleNamespace(passed=True, issues=(), metrics={"error_count": 0})

    async def fake_pwiki_002(
        connection: Any, **kwargs: Any
    ) -> SimpleNamespace:
        """PWIKI-002 facade 호출을 기록하고 저장 결과를 반환한다."""
        order.append("persist")
        assert kwargs["plan"] is plan
        assert kwargs["job_id"] == "job-1"
        return _fake_persisted()

    async def fake_wba_011(connection: Any, **kwargs: Any) -> int:
        """변경 Chunk Embedding 갱신 순서를 기록한다."""
        order.append("embed")
        assert kwargs["document_version_ids"] == ["doc-version-1"]
        return 1

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
    monkeypatch.setattr(
        agent_graph, "list_onboarding_wiki_anchor_keys", fake_entries
    )
    monkeypatch.setattr(agent_graph, "list_wiki_node_embeddings", fake_entries)
    monkeypatch.setattr(agent_graph, "classify_source_for_wiki", fake_classify)
    monkeypatch.setattr(
        agent_graph, "prepare_wiki_identity_resolution", fake_prepare_identity
    )
    monkeypatch.setattr(
        agent_graph, "resolve_wiki_identity_conflicts", fake_resolve_identity
    )
    monkeypatch.setattr(agent_graph, "validate_wiki_identity_quality", fake_quality_gate)
    monkeypatch.setattr(agent_graph, "wba_003", fake_wba_003)
    monkeypatch.setattr(agent_graph, "wba_014", fake_plan_quality)
    monkeypatch.setattr(agent_graph, "wba_011", fake_wba_011)
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

    assert order == [
        "load_source",
        "classify",
        "prepare_identity",
        "resolve_identity",
        "quality_gate",
        "plan",
        "validate_plan",
        "persist",
        "embed",
        "recalculate",
    ]
    assert result["source_document_id"] == "source-1"
    assert result["wiki_version_id"] == "wiki-version-1"
    assert result["chunk_count"] == 2
    assert result["extracted_relation_count"] == 2
    assert result["stored_relation_count"] == 4
    assert result["isolated_node_count"] == 1
    assert result["relation_warnings"] == ["관계 경고"]
    assert result["identity_resolution"] == {
        "model": "test-resolver",
        "resolved_conflict_count": 1,
        "input_tokens": 120,
        "output_tokens": 30,
    }
    assert result["embedding_count"] == 1
    assert result["affected_documents"][0]["document_key"] == "entity-key"
    assert result["artifacts"]["index"] == "index"


def test_run_personal_wiki_build_materializes_onboarding_labels_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실제 Worker 그래프도 온보딩 라벨을 결정적으로 Concept로 만든다."""
    captured: dict[str, Any] = {}
    plan = SimpleNamespace(
        entities=[],
        concepts=[],
        relations=[],
        node_dispositions=[],
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

    def fail_if_identity_llm_is_called(**kwargs: Any) -> object:
        """표면형 충돌이 없는 온보딩에서 identity LLM 실행을 금지한다."""
        raise AssertionError("온보딩 원자 주제는 identity LLM을 호출하면 안 됩니다.")

    async def fake_wba_003(**kwargs: Any) -> SimpleNamespace:
        """결정적 분류 결과와 모델 표식을 기록한다."""
        captured["classification"] = kwargs["classification"]
        captured["model"] = kwargs["model"]
        return plan

    async def fake_pwiki_002(connection: Any, **kwargs: Any) -> SimpleNamespace:
        """고정 저장 결과를 반환한다."""
        return _fake_persisted()

    async def fake_embedding(connection: Any, **kwargs: Any) -> int:
        """테스트에서 외부 Embedding 호출을 생략한다."""
        return 1

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
    monkeypatch.setattr(
        agent_graph, "list_onboarding_wiki_anchor_keys", fake_listing
    )
    monkeypatch.setattr(agent_graph, "list_wiki_node_embeddings", fake_listing)
    monkeypatch.setattr(agent_graph, "classify_source_for_wiki", fail_if_llm_is_called)
    monkeypatch.setattr(
        agent_graph, "resolve_wiki_identity_conflicts", fail_if_identity_llm_is_called
    )
    monkeypatch.setattr(agent_graph, "wba_003", fake_wba_003)
    monkeypatch.setattr(agent_graph, "pwiki_002", fake_pwiki_002)
    monkeypatch.setattr(agent_graph, "wba_011", fake_embedding)
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
    assert captured["model"] == (
        "deterministic:onboarding-seed-v1;identity=deterministic:wiki-surface-v1;"
        "relation=deterministic:onboarding-anchor-v1"
    )
    assert result["identity_resolution"]["resolved_conflict_count"] == 0
    assert result["wiki_version_id"] == "wiki-version-1"


def test_run_personal_wiki_build_survives_interest_recalc_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """관심사 재계산 훅이 실패해도 Build 결과 Payload는 그대로 반환된다."""
    plan = SimpleNamespace(
        entities=[],
        concepts=[],
        relations=[],
        node_dispositions=[],
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

    classification = WikiClassification()

    def fake_prepare_identity(**kwargs: Any) -> SimpleNamespace:
        """충돌이 없는 고정 identity 초안을 반환한다."""
        return SimpleNamespace(classification=classification, conflicts=())

    def fake_quality_gate(**kwargs: Any) -> str:
        """고정 분류 결과를 저장 전 검증에서 통과시킨다."""
        return kwargs["classification"]

    async def fake_pwiki_002(connection: Any, **kwargs: Any) -> SimpleNamespace:
        """고정 저장 결과를 반환한다."""
        return _fake_persisted()

    async def fake_embedding(connection: Any, **kwargs: Any) -> int:
        """테스트에서 외부 Embedding 호출을 생략한다."""
        return 1

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
        agent_graph, "list_onboarding_wiki_anchor_keys", fake_listing
    )
    monkeypatch.setattr(agent_graph, "list_wiki_node_embeddings", fake_listing)
    monkeypatch.setattr(
        agent_graph, "classify_source_for_wiki", lambda **kwargs: classification
    )
    monkeypatch.setattr(
        agent_graph, "prepare_wiki_identity_resolution", fake_prepare_identity
    )
    monkeypatch.setattr(agent_graph, "validate_wiki_identity_quality", fake_quality_gate)
    monkeypatch.setattr(agent_graph, "wba_003", fake_wba_003)
    monkeypatch.setattr(agent_graph, "pwiki_002", fake_pwiki_002)
    monkeypatch.setattr(agent_graph, "wba_011", fake_embedding)
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
    monkeypatch.setattr(agent_graph, "embed_wiki_queries", lambda queries: {})
    _disable_critic(monkeypatch)


def test_wiki_keyword_expansion_uses_bounded_ppr_and_excludes_organizations() -> None:
    """성숙한 Snapshot은 2-hop PPR을 쓰고 조직·3-hop·top_k 초과를 제외한다."""
    snapshot = [
        _graph_snapshot_relation("weather", "날씨", "heatwave", "폭염"),
        _graph_snapshot_relation("heatwave", "폭염", "illness", "온열질환"),
        _graph_snapshot_relation("weather", "날씨", "typhoon", "태풍"),
        _graph_snapshot_relation("typhoon", "태풍", "surge", "폭풍해일"),
        _graph_snapshot_relation("heatwave", "폭염", "typhoon", "태풍"),
        _graph_snapshot_relation("surge", "폭풍해일", "coast", "해안"),
        _graph_snapshot_relation(
            "weather",
            "날씨",
            "agency",
            "기상 기관",
            target_domain="organization",
            weight=10.0,
        ),
    ]

    expansion = agent_graph._expand_wiki_graph_keywords(
        "날씨",
        snapshot,
        top_k=3,
    )

    assert expansion.gate_passed is True
    assert expansion.mode == "bounded_ppr"
    assert len(expansion.keywords) == 3
    assert "기상 기관" not in expansion.keywords
    assert "해안" not in expansion.keywords
    assert set(expansion.keywords) <= {"폭염", "온열질환", "태풍", "폭풍해일"}


def test_wiki_keyword_expansion_gate_failure_uses_verified_one_hop_only() -> None:
    """Gate 실패 시 accepted·supported·confidence 통과 직접 이웃만 반환한다."""
    snapshot = [
        _graph_snapshot_relation(
            "weather",
            "날씨",
            "heatwave",
            "폭염",
            provenance_kind="semantic_inference",
            confidence=0.84,
        ),
        _graph_snapshot_relation(
            "weather",
            "날씨",
            "finance",
            "금융",
            provenance_kind="semantic_inference",
            confidence=0.77,
        ),
        _graph_snapshot_relation(
            "weather",
            "날씨",
            "festival",
            "축제",
            review_status="unreviewed",
        ),
        _graph_snapshot_relation(
            "weather",
            "날씨",
            "unsupported",
            "근거 없음",
            supported=False,
        ),
    ]

    expansion = agent_graph._expand_wiki_graph_keywords(
        "weather",
        snapshot,
        top_k=5,
    )

    assert expansion.gate_passed is False
    assert expansion.mode == "one_hop"
    assert expansion.keywords == ("폭염",)
    assert any("검증 Edge" in reason for reason in expansion.maturity_reasons)


def test_graph_snapshot_query_failure_uses_legacy_one_hop_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Migration 미적용 등 Snapshot 조회 실패에서만 기존 1-hop SQL로 폴백한다."""
    calls: list[str] = []

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """테스트 DB Scope 설정 호출을 기록한다."""
        calls.append(f"scope:{user_id}")

    async def fail_snapshot(connection: Any, **kwargs: Any) -> list[object]:
        """Migration 전 UndefinedColumn 조회 실패를 재현한다."""
        calls.append("snapshot")
        raise RuntimeError("undefined column relation.status")

    async def fake_legacy(connection: Any, **kwargs: Any) -> list[SimpleNamespace]:
        """신규 lifecycle SQL 실패 뒤 구버전 1-hop SQL에서 이웃을 반환한다."""
        lifecycle_aware = bool(kwargs["lifecycle_aware"])
        calls.append(f"legacy:{lifecycle_aware}")
        assert kwargs["limit"] == 2
        if lifecycle_aware:
            raise RuntimeError("undefined column relation.status")
        return [SimpleNamespace(title="폭염"), SimpleNamespace(title="태풍")]

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        agent_graph,
        "list_wiki_graph_relation_snapshot",
        fail_snapshot,
    )
    monkeypatch.setattr(agent_graph, "list_related_wiki_keywords", fake_legacy)
    connection = _FakeConnection()

    expansion = asyncio.run(
        agent_graph._load_related_keyword_expansion(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic="날씨",
            top_k=2,
        )
    )

    assert expansion.mode == "legacy_one_hop"
    assert expansion.keywords == ("폭염", "태풍")
    assert calls == [
        "scope:user-1",
        "snapshot",
        "scope:user-1",
        "legacy:True",
        "scope:user-1",
        "legacy:False",
    ]
    assert connection.transactions == 3


def test_successful_graph_snapshot_never_calls_legacy_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshot 조회가 성공한 Gate 실패는 기존 SQL이 아닌 검증 1-hop을 쓴다."""

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """테스트에서는 DB Scope 설정을 생략한다."""

    async def fake_snapshot(
        connection: Any, **kwargs: Any
    ) -> list[WikiGraphRelationSnapshot]:
        """검증 Edge 한 건인 미성숙 Graph를 반환한다."""
        return [_graph_snapshot_relation("weather", "날씨", "heatwave", "폭염")]

    async def fail_legacy(connection: Any, **kwargs: Any) -> list[object]:
        """성공한 Snapshot 뒤 기존 조회가 호출되면 테스트를 실패시킨다."""
        raise AssertionError("legacy 1-hop must not be called")

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        agent_graph,
        "list_wiki_graph_relation_snapshot",
        fake_snapshot,
    )
    monkeypatch.setattr(agent_graph, "list_related_wiki_keywords", fail_legacy)
    connection = _FakeConnection()

    expansion = asyncio.run(
        agent_graph._load_related_keyword_expansion(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            topic="날씨",
            top_k=1,
        )
    )

    assert expansion.mode == "one_hop"
    assert expansion.keywords == ("폭염",)
    assert connection.transactions == 1


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

    async def fake_graph_snapshot(
        connection: Any, **kwargs: Any
    ) -> list[WikiGraphRelationSnapshot]:
        """Wiki Graph Snapshot 조회를 미성숙 검증 Edge 한 건으로 대체한다."""
        order.append("related_keywords")
        assert kwargs["namespace_key"] == "user/user-1"
        return [
            _graph_snapshot_relation(
                "personalization",
                "개인화",
                "recommendation",
                "추천 시스템",
            )
        ]

    async def fail_legacy_query(connection: Any, **kwargs: Any) -> list[object]:
        """Snapshot 성공 뒤 기존 1-hop SQL을 호출하면 테스트를 실패시킨다."""
        raise AssertionError("legacy 1-hop must not be called")

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
        agent_graph, "list_wiki_graph_relation_snapshot", fake_graph_snapshot
    )
    monkeypatch.setattr(agent_graph, "list_related_wiki_keywords", fail_legacy_query)
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
    monkeypatch.setattr(agent_graph, "embed_wiki_queries", lambda queries: {})
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


def test_interest_bundle_snapshot_reaches_research_and_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """그래프는 Job의 연결 키워드를 조사 계획과 루트 중심 생성에 그대로 전달한다."""
    order: list[str] = []
    _patch_generation_tail(monkeypatch, order)
    generated_with: dict[str, Any] = {}
    bundle = {
        "root": {
            "keyword": "생성형 AI",
            "documents": [{"document_version_id": "version-root"}],
        },
        "neighbors": [
            {"keyword": "AI 에이전트", "document_version_id": "version-agent"},
            {"keyword": "RAG", "document_version_id": "version-rag"},
        ],
        "keywords": ["생성형 AI", "AI 에이전트", "RAG"],
    }
    pinned = ReportContextDocument(
        reference="P1",
        document_version_id="version-root",
        chunk_id="chunk-root",
        namespace_key="user/user-1",
        title="생성형 AI",
        content="Job 접수 시 고정한 Wiki 맥락",
        url=None,
        score=1.0,
        context_role="wiki_root",
        source_updated_at="2026-08-09T10:00:00+00:00",
    )
    researched = ReportContextDocument(
        reference="G1",
        document_version_id="global-1",
        chunk_id="global-chunk-1",
        namespace_key="global",
        title="생성형 AI 최신 기사",
        content="새 모델 발표",
        url="https://example.com/latest",
        score=0.9,
    )

    async def fake_pinned_context(connection: Any, **kwargs: Any) -> list[Any]:
        """고정 Wiki Version을 직접 읽은 결과를 반환한다."""
        assert kwargs["interest_bundle"] == bundle
        return [pinned]

    async def fake_research(connection: Any, **kwargs: Any) -> Any:
        """조사원이 전달받은 결정적 연결 키워드를 검증한다."""
        assert kwargs["planned_queries"] == ["AI 에이전트", "RAG"]
        return SimpleNamespace(
            documents=(researched,),
            calls=(),
            collected_live=False,
            notes="묶음 조사 완료",
            stop_reason="final",
        )

    def fake_generate(**kwargs: Any) -> str:
        """생성기에 전달된 관심사 묶음 스냅샷을 기록한다."""
        generated_with.update(kwargs)
        return "generated"

    monkeypatch.setattr(agent_graph, "research_agent_enabled", lambda: True)
    monkeypatch.setattr(agent_graph, "research_context", fake_research)
    monkeypatch.setattr(agent_graph, "load_pinned_wiki_context", fake_pinned_context)
    monkeypatch.setattr(
        agent_graph, "generate_report_content_with_quality", fake_generate
    )

    asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="생성형 AI",
            content_type="interest_news_card",
            language="ko",
            generation_scope="INTEREST_BUNDLE",
            interest_bundle=bundle,
        )
    )

    assert generated_with["interest_bundle"] == bundle
    assert generated_with["topic"] == "생성형 AI"
    assert [context.context_role for context in generated_with["contexts"]] == [
        "wiki_root",
        "retrieved",
    ]
    assert generated_with["contexts"][0].document_version_id == "version-root"


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

    async def fake_global_search(connection: Any, **kwargs: Any) -> list[str]:
        """Reader 실패 폴백의 Global 전용 검색을 대체한다."""
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
    monkeypatch.setattr(agent_graph, "search_global_documents", fake_global_search)
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

    async def fake_global_search(connection: Any, **kwargs: Any) -> list[str]:
        """빈 Reader 결과 뒤 Global 전용 검색을 대체한다."""
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
    monkeypatch.setattr(agent_graph, "search_global_documents", fake_global_search)
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
    # 대체하지 않으면 네이버·구글·유튜브·OpenAI를 실제로 호출한다.
    monkeypatch.setattr(agent_graph, "collect_live_context", lambda *a, **k: [])
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
    assert result["content_candidate_id"] == "candidate-1"
    # 주제별 근거 단계 건수를 결과에 남긴다. 섹션이 빠졌을 때 어디서 근거를
    # 잃었는지 서버 로그 없이 확인하려면 이 값이 필요하다(2026-08-11: '폭염'
    # 섹션이 사라진 원인을 못 찾아 리포트를 네 번 다시 돌렸다).
    assert [entry["topic"] for entry in result["evidence_trace"]] == [
        "반도체",
        "프로야구",
    ]
    assert all(
        set(entry) >= {"gathered", "after_focus", "selected", "picked", "quota"}
        for entry in result["evidence_trace"]
    )
    # 단계별 소요 시간도 함께 남긴다. 3주제 리포트가 1615초 걸렸는데 본문 생성은
    # 5.2초였다 — 나머지가 어디로 갔는지 이 값으로 가른다.
    assert all(
        "total" in entry["elapsed_ms"] for entry in result["evidence_trace"]
    )


def test_multi_topic_report_drops_topics_without_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """근거를 한 건도 못 구한 주제는 생성 프롬프트에서 뺀다.

    남겨 두면 "소주제를 순서대로 빠짐없이 다루라"는 지시 때문에 LLM이 근거 없는
    일반론으로 그 섹션을 채운다(2026-08-10 실측: '환율' 섹션이 "구체적인 정보는
    제공되지 않았습니다. 그러나 변동성이 높아지고 있는 상황이므로..."가 됐다).
    """
    generated_with: dict[str, Any] = {}

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """DB 사용자 Scope 설정을 생략한다."""
        return None

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[str]:
        """'환율'만 검색 결과가 없는 상황을 만든다."""
        query = kwargs["query"]
        return [] if query == "환율" else [f"context-{query}"]

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
    # 대체하지 않으면 네이버·구글·유튜브·OpenAI를 실제로 호출한다.
    monkeypatch.setattr(agent_graph, "collect_live_context", lambda *a, **k: [])
    _disable_research(monkeypatch)

    asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="오늘의 관심사 요약",
            topics=["반도체", "환율", "프로야구"],
            content_type="interest_news_card",
            language="ko",
            model="test-model",
        )
    )

    # 근거가 붙은 두 주제만 프롬프트로 간다.
    assert generated_with["topics"] == ["반도체", "프로야구"]
    assert generated_with["contexts"] == ["context-반도체", "context-프로야구"]


def test_multi_topic_report_collects_live_when_the_pool_is_thin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """창고가 부족한 주제는 실시간 수집으로 근거를 채운다.

    처음엔 여러 주제 경로에서 실시간 수집을 아예 뺐다. "조사원이 이미 수집을
    시도했다"고 봤는데 틀렸다 — 조사원에게는 search_pool만 주고 collect_live는
    도구로 노출하지 않는다. 그래서 창고에 없는 주제는 영영 근거가 0건이었다
    (2026-08-10 실측: '환율' 섹션이 통째로 빠졌다).
    """
    collected: list[str] = []
    expanded: dict[str, list[str]] = {}
    generated_with: dict[str, Any] = {}

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """DB 사용자 Scope 설정을 생략한다."""
        return None

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[str]:
        """창고가 비어 있는 상황을 만든다."""
        return []

    async def fake_expansion(connection: Any, **kwargs: Any) -> Any:
        """주제마다 Wiki 이웃 키워드를 하나씩 돌려준다."""
        return SimpleNamespace(
            keywords=(f"{kwargs['topic']}-이웃",),
            mode="verified_one_hop",
            gate_passed=True,
            maturity_reasons=(),
        )

    async def fake_prag_006(contexts: list[str]) -> list[str]:
        """검색 Context를 변경 없이 반환한다."""
        return contexts

    def fake_collect(topic: str, user_id: str, **kwargs: Any) -> list[str]:
        """실시간 수집을 대체하고 주제·이웃 키워드를 기록한다."""
        collected.append(topic)
        expanded[topic] = list(kwargs.get("related_keywords") or [])
        return [f"live-{topic}"]

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
    monkeypatch.setattr(agent_graph, "collect_live_context", fake_collect)
    monkeypatch.setattr(
        agent_graph, "_load_related_keyword_expansion", fake_expansion
    )
    monkeypatch.setattr(agent_graph, "generate_report_content_with_quality", fake_generate)
    monkeypatch.setattr(agent_graph, "prag_007", fake_prag_007)
    _disable_research(monkeypatch)

    asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="오늘의 관심사 요약",
            topics=["반도체", "환율"],
            content_type="interest_news_card",
            language="ko",
            model="test-model",
        )
    )

    assert collected == ["반도체", "환율"]
    assert generated_with["contexts"] == ["live-반도체", "live-환율"]
    # 주제 이름 하나로만 수집하면 '코스피' 리포트에 코스닥시장 기사가 안 걸린다.
    # 단일 주제 경로와 같은 Wiki 이웃 확장을 주제마다 적용한다.
    assert expanded == {"반도체": ["반도체-이웃"], "환율": ["환율-이웃"]}


def test_multi_topic_report_uses_matched_bundle_for_one_topic_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """여러 독립 주제 중 접수 시 매칭된 주제만 스냅샷 구조를, 나머지는 반응형 검색을 쓴다.

    interest-bundle-report-design.md §9 — topics의 독립 섹션 원칙(연결 노드를 묶어
    섹션화하지 않는다)은 그대로 두고, 주제별 매칭 여부만 각자 판정한다.
    """
    pinned_calls: list[str] = []
    searched: dict[str, list[str]] = {"코스피": [], "환율": []}
    expansion_calls: list[str] = []
    collected_with: dict[str, list[str]] = {}
    bundle = {
        "root": {
            "keyword": "코스피",
            "documents": [{"document_version_id": "version-root"}],
        },
        "neighbors": [
            {"keyword": "코스닥시장", "document_version_id": "version-neighbor"},
        ],
        "keywords": ["코스피", "코스닥시장"],
    }

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """DB 사용자 Scope 설정을 생략한다."""

    async def fake_pinned_context(connection: Any, **kwargs: Any) -> list[Any]:
        """매칭된 주제에서만 호출되는지 루트 키워드를 기록한다."""
        interest_bundle = kwargs["interest_bundle"] or {}
        pinned_calls.append(str(interest_bundle["root"]["keyword"]))
        return []

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[Any]:
        """창고가 비어 있는 상황을 만들고 검색어를 주제별로 기록한다."""
        query = str(kwargs["query"])
        topic_key = "코스피" if query in ("코스피", "코스닥시장") else "환율"
        searched[topic_key].append(query)
        return []

    async def fake_freshness(connection: Any, ids: list[str]) -> dict[str, Any]:
        """Global 문서가 없는 검색 결과의 신선도 조회를 생략한다."""
        return {}

    async def fake_prag_006(contexts: list[Any]) -> list[Any]:
        """맥락화 단계를 통과시킨다."""
        return contexts

    async def fake_expansion(connection: Any, **kwargs: Any) -> Any:
        """매칭 안 된 주제만 반응형 1홉 검색을 호출한다."""
        expansion_calls.append(kwargs["topic"])
        return SimpleNamespace(
            keywords=("환헤지",),
            mode="verified_one_hop",
            gate_passed=True,
            maturity_reasons=(),
        )

    def fake_collect(topic: str, user_id: str, **kwargs: Any) -> list[str]:
        """실시간 수집에 주제별로 어떤 이웃 키워드가 전달되는지 기록한다."""
        collected_with[topic] = list(kwargs.get("related_keywords") or [])
        return [f"live-{topic}"]

    def fake_generate(**kwargs: Any) -> str:
        """고정 콘텐츠를 반환한다."""
        return "generated"

    async def fake_prag_007(connection: Any, **kwargs: Any) -> dict[str, object]:
        """저장 호출을 고정 결과로 대체한다."""
        return {"content_candidate_id": "candidate-1"}

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "load_pinned_wiki_context", fake_pinned_context)
    monkeypatch.setattr(agent_graph, "prag_003", fake_prag_003)
    monkeypatch.setattr(agent_graph, "load_global_document_freshness", fake_freshness)
    monkeypatch.setattr(agent_graph, "prag_006", fake_prag_006)
    monkeypatch.setattr(
        agent_graph, "_load_related_keyword_expansion", fake_expansion
    )
    monkeypatch.setattr(agent_graph, "collect_live_context", fake_collect)
    monkeypatch.setattr(
        agent_graph, "generate_report_content_with_quality", fake_generate
    )
    monkeypatch.setattr(agent_graph, "prag_007", fake_prag_007)
    _disable_research(monkeypatch)

    asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="오늘의 관심사 요약",
            topics=["코스피", "환율"],
            content_type="interest_news_card",
            language="ko",
            model="test-model",
            topic_interest_bundles={"코스피": bundle},
        )
    )

    assert pinned_calls == ["코스피"]
    assert searched == {"코스피": ["코스피", "코스닥시장"], "환율": ["환율"]}
    assert expansion_calls == ["환율"]
    assert collected_with == {"코스피": ["코스닥시장"], "환율": ["환헤지"]}


def test_multi_topic_report_caps_live_collection_per_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """한 리포트에서 실시간 수집을 도는 주제 수에 상한을 둔다.

    수집 한 번이 뉴스·YouTube·Reddit 호출과 LLM 요약을 포함해 수십 초 걸린다.
    주제 수만큼 돌리면 Worker lease(600초)를 넘겨 같은 Job이 죽은 것으로 판정되고
    리포트가 중복 생성된다. 아침·온디맨드가 보내는 3개까지는 전부 채우고, 계약
    상한인 5개가 오면 거기서 끊는다.
    """
    collected: list[str] = []

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """DB 사용자 Scope 설정을 생략한다."""
        return None

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[str]:
        """창고가 비어 있는 상황을 만든다."""
        return []

    async def fake_prag_006(contexts: list[str]) -> list[str]:
        """검색 Context를 변경 없이 반환한다."""
        return contexts

    def fake_collect(topic: str, user_id: str, **_kwargs: Any) -> list[str]:
        """실시간 수집을 대체하고 주제를 기록한다."""
        collected.append(topic)
        return [f"live-{topic}"]

    def fake_generate(**kwargs: Any) -> str:
        """고정 콘텐츠를 반환한다."""
        return "generated"

    async def fake_prag_007(connection: Any, **kwargs: Any) -> dict[str, object]:
        """저장 호출을 고정 결과로 대체한다."""
        return {"content_candidate_id": "candidate-1"}

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "prag_003", fake_prag_003)
    monkeypatch.setattr(agent_graph, "prag_006", fake_prag_006)
    monkeypatch.setattr(agent_graph, "collect_live_context", fake_collect)
    monkeypatch.setattr(agent_graph, "generate_report_content_with_quality", fake_generate)
    monkeypatch.setattr(agent_graph, "prag_007", fake_prag_007)
    _disable_research(monkeypatch)

    asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="오늘의 관심사 요약",
            topics=["반도체", "환율", "프로야구", "웹툰", "금리"],
            content_type="interest_news_card",
            language="ko",
            model="test-model",
        )
    )

    assert collected == ["반도체", "환율", "프로야구"]


def test_live_budget_is_spent_only_when_collection_actually_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """창고로 해결된 주제는 실시간 수집 예산을 쓰지 않는다.

    무조건 깎으면 앞 주제들이 수집을 한 번도 안 했는데도 뒤쪽 주제가 예산 부족으로
    못 돈다. 상한(3)보다 주제가 많을 때 실제로 필요한 주제가 밀려난다.
    """
    collected: list[str] = []

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """DB 사용자 Scope 설정을 생략한다."""
        return None

    def pool_doc(topic: str, index: int) -> ReportContextDocument:
        """창고 판정을 통과할 수 있는 풀 문서 하나를 만든다."""
        reference = f"G{topic}{index}"
        return ReportContextDocument(
            reference=reference,
            document_version_id=f"ver-{reference}",
            chunk_id=f"chunk-{reference}",
            namespace_key="global",
            title=f"{topic} 기사 {index}",
            content=f"{topic} 관련 본문",
            url=f"https://example.com/{reference}",
            score=0.5,
        )

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[Any]:
        """'금리'만 창고가 비어 있고 나머지는 충분한 풀 자료가 잡히게 한다."""
        query = kwargs["query"]
        if query == "금리":
            return []
        # POOL_MIN_DOCUMENTS(3)을 넘겨야 "창고가 충분하다"로 판정된다.
        return [pool_doc(query, index) for index in range(3)]

    async def fake_prag_006(contexts: list[str]) -> list[str]:
        """검색 Context를 변경 없이 반환한다."""
        return contexts

    def fake_collect(topic: str, user_id: str, **_kwargs: Any) -> list[str]:
        """실시간 수집을 대체하고 주제를 기록한다."""
        collected.append(topic)
        return [f"live-{topic}"]

    def fake_generate(**kwargs: Any) -> str:
        """고정 콘텐츠를 반환한다."""
        return "generated"

    async def fake_prag_007(connection: Any, **kwargs: Any) -> dict[str, object]:
        """저장 호출을 고정 결과로 대체한다."""
        return {"content_candidate_id": "candidate-1"}

    async def fake_freshness(connection: Any, ids: Any) -> dict[str, Any]:
        """발행일 조회를 생략한다(신선도 검사는 이 테스트의 대상이 아니다)."""
        return {}

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "prag_003", fake_prag_003)
    monkeypatch.setattr(agent_graph, "prag_006", fake_prag_006)
    monkeypatch.setattr(agent_graph, "load_global_document_freshness", fake_freshness)
    monkeypatch.setattr(agent_graph, "collect_live_context", fake_collect)
    monkeypatch.setattr(agent_graph, "generate_report_content_with_quality", fake_generate)
    monkeypatch.setattr(agent_graph, "prag_007", fake_prag_007)
    # 주제 관련성 판정은 임베딩을 부르므로 대역으로 바꾼다.
    monkeypatch.setattr(agent_graph, "is_pool_relevant", lambda *a, **k: True)
    _disable_research(monkeypatch)

    asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="오늘의 관심사 요약",
            # 상한(3)보다 많은 5개. 앞 넷은 창고에 자료가 있어 수집이 필요 없다.
            topics=["반도체", "환율", "프로야구", "웹툰", "금리"],
            content_type="interest_news_card",
            language="ko",
            model="test-model",
        )
    )

    # 앞 넷이 예산을 먹지 않았으므로 마지막 주제도 수집할 수 있다.
    assert collected == ["금리"]


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


def test_interest_bundle_fixed_path_searches_snapshot_keywords_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """조사원을 꺼도 루트·스냅샷 이웃을 검색하고 현재 Wiki 이웃은 다시 읽지 않는다."""
    searched: list[str] = []
    collected_with: list[str] = []
    generated_with: dict[str, Any] = {}
    bundle = {
        "root": {
            "keyword": "생성형 AI",
            "documents": [{"document_version_id": "version-root"}],
        },
        "neighbors": [
            {"keyword": "AI 에이전트", "document_version_id": "version-agent"},
            {"keyword": "RAG", "document_version_id": "version-rag"},
        ],
        "keywords": ["생성형 AI", "AI 에이전트", "RAG"],
    }

    async def fake_pinned_context(connection: Any, **kwargs: Any) -> list[Any]:
        """고정 루트 Version을 검색 결과보다 먼저 반환한다."""
        return [
            ReportContextDocument(
                reference="P1",
                document_version_id="version-root",
                chunk_id="chunk-root",
                namespace_key="user/user-1",
                title="생성형 AI 기준 지식",
                content="사용자가 저장한 기존 맥락",
                url=None,
                score=1.0,
                context_role="wiki_root",
            )
        ]

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """DB 사용자 Scope 설정을 생략한다."""

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[Any]:
        """검색어마다 고유한 개인 Wiki 근거를 반환한다."""
        query = kwargs["query"]
        searched.append(query)
        number = len(searched)
        return [
            ReportContextDocument(
                reference="P1",
                document_version_id=f"version-{number}",
                chunk_id=f"chunk-{number}",
                namespace_key="user/user-1",
                title=query,
                content=f"{query} 근거",
                url=None,
                score=0.9,
            )
        ]

    async def fake_freshness(connection: Any, ids: list[str]) -> dict[str, Any]:
        """Global 문서가 없는 검색 결과의 신선도 조회를 생략한다."""
        return {}

    async def fake_prag_006(contexts: list[Any]) -> list[Any]:
        """맥락화 단계를 통과시킨다."""
        return contexts

    async def fail_related(*args: Any, **kwargs: Any) -> list[Any]:
        """현재 Wiki 이웃을 다시 조회하면 테스트를 실패시킨다."""
        raise AssertionError("스냅샷 범주는 현재 Wiki 이웃을 다시 조회하면 안 된다.")

    def fake_collect(topic: str, user_id: str, **kwargs: Any) -> list[Any]:
        """실시간 수집에 스냅샷 이웃이 전달되는지 기록한다."""
        collected_with.extend(kwargs["related_keywords"])
        return []

    def fake_generate(**kwargs: Any) -> str:
        """생성 입력을 기록한다."""
        generated_with.update(kwargs)
        return "generated"

    async def fake_persist(connection: Any, **kwargs: Any) -> dict[str, object]:
        """저장 결과를 고정한다."""
        return {"content_candidate_id": "candidate-1"}

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "load_pinned_wiki_context", fake_pinned_context)
    monkeypatch.setattr(agent_graph, "prag_003", fake_prag_003)
    monkeypatch.setattr(agent_graph, "load_global_document_freshness", fake_freshness)
    monkeypatch.setattr(agent_graph, "prag_006", fake_prag_006)
    monkeypatch.setattr(agent_graph, "list_related_wiki_keywords", fail_related)
    monkeypatch.setattr(agent_graph, "collect_live_context", fake_collect)
    monkeypatch.setattr(
        agent_graph, "generate_report_content_with_quality", fake_generate
    )
    monkeypatch.setattr(agent_graph, "prag_007", fake_persist)
    _disable_research(monkeypatch)

    asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="생성형 AI",
            content_type="interest_news_card",
            language="ko",
            generation_scope="INTEREST_BUNDLE",
            interest_bundle=bundle,
        )
    )

    assert searched == ["생성형 AI", "AI 에이전트", "RAG"]
    assert collected_with == ["AI 에이전트", "RAG"]
    assert [context.reference for context in generated_with["contexts"]] == [
        "P1",
        "P2",
        "P3",
        "P4",
    ]
    assert generated_with["contexts"][0].context_role == "wiki_root"
    assert generated_with["contexts"][0].title == "생성형 AI 기준 지식"
    assert generated_with["interest_bundle"] == bundle


def test_single_topic_uses_matched_interest_bundle_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SINGLE_TOPIC 주제가 접수 시 INT-013으로 매칭됐으면 스냅샷 구조를 쓴다.

    interest-bundle-report-design.md §9 — 반응형 1홉 검색(list_related_wiki_keywords)
    대신 접수 시 고정한 topic_interest_bundles의 루트·이웃 키워드로 검색한다.
    """
    searched: list[str] = []
    collected_with: list[str] = []
    bundle = {
        "root": {
            "keyword": "코스피",
            "documents": [{"document_version_id": "version-root"}],
        },
        "neighbors": [
            {"keyword": "코스닥시장", "document_version_id": "version-neighbor"},
        ],
        "keywords": ["코스피", "코스닥시장"],
    }

    async def fake_pinned_context(connection: Any, **kwargs: Any) -> list[Any]:
        """고정 루트 Version을 검색 결과보다 먼저 반환한다."""
        return [
            ReportContextDocument(
                reference="P1",
                document_version_id="version-root",
                chunk_id="chunk-root",
                namespace_key="user/user-1",
                title="코스피 기준 지식",
                content="사용자가 저장한 기존 맥락",
                url=None,
                score=1.0,
                context_role="wiki_root",
            )
        ]

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """DB 사용자 Scope 설정을 생략한다."""

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[Any]:
        """검색어마다 고유한 개인 Wiki 근거를 반환한다."""
        query = kwargs["query"]
        searched.append(query)
        number = len(searched)
        return [
            ReportContextDocument(
                reference="P1",
                document_version_id=f"version-{number}",
                chunk_id=f"chunk-{number}",
                namespace_key="user/user-1",
                title=query,
                content=f"{query} 근거",
                url=None,
                score=0.9,
            )
        ]

    async def fake_freshness(connection: Any, ids: list[str]) -> dict[str, Any]:
        """Global 문서가 없는 검색 결과의 신선도 조회를 생략한다."""
        return {}

    async def fake_prag_006(contexts: list[Any]) -> list[Any]:
        """맥락화 단계를 통과시킨다."""
        return contexts

    async def fail_related(*args: Any, **kwargs: Any) -> list[Any]:
        """현재 Wiki 이웃을 다시 조회하면 테스트를 실패시킨다."""
        raise AssertionError("스냅샷 범주는 현재 Wiki 이웃을 다시 조회하면 안 된다.")

    def fake_collect(topic: str, user_id: str, **kwargs: Any) -> list[Any]:
        """실시간 수집에 스냅샷 이웃이 전달되는지 기록한다."""
        collected_with.extend(kwargs["related_keywords"])
        return []

    def fake_generate(**kwargs: Any) -> str:
        """생성 입력을 기록한다."""
        return "generated"

    async def fake_persist(connection: Any, **kwargs: Any) -> dict[str, object]:
        """저장 결과를 고정한다."""
        return {"content_candidate_id": "candidate-1"}

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "load_pinned_wiki_context", fake_pinned_context)
    monkeypatch.setattr(agent_graph, "prag_003", fake_prag_003)
    monkeypatch.setattr(agent_graph, "load_global_document_freshness", fake_freshness)
    monkeypatch.setattr(agent_graph, "prag_006", fake_prag_006)
    monkeypatch.setattr(agent_graph, "list_related_wiki_keywords", fail_related)
    monkeypatch.setattr(agent_graph, "collect_live_context", fake_collect)
    monkeypatch.setattr(
        agent_graph, "generate_report_content_with_quality", fake_generate
    )
    monkeypatch.setattr(agent_graph, "prag_007", fake_persist)
    _disable_research(monkeypatch)

    asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="코스피",
            content_type="interest_news_card",
            language="ko",
            topic_interest_bundles={"코스피": bundle},
        )
    )

    assert searched == ["코스피", "코스닥시장"]
    assert collected_with == ["코스닥시장"]


def test_single_topic_falls_back_to_reactive_search_without_a_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """접수 시 매칭된 관심사가 없으면 고정 Wiki 없이 기존 반응형 1홉 검색을 쓴다."""
    searched: list[str] = []
    expansion_calls: list[str] = []
    collected_with: list[str] = []

    async def fake_pinned_context(connection: Any, **kwargs: Any) -> list[Any]:
        """호출되면 테스트를 실패시킨다 — 매칭이 없으면 고정 Wiki를 읽지 않는다."""
        raise AssertionError("매칭 없는 주제는 고정 Wiki Version을 읽으면 안 된다.")

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """DB 사용자 Scope 설정을 생략한다."""

    async def fake_prag_003(connection: Any, **kwargs: Any) -> list[Any]:
        """검색어를 기록하고 빈 결과를 반환해 실시간 수집으로 넘어가게 한다."""
        searched.append(kwargs["query"])
        return []

    async def fake_freshness(connection: Any, ids: list[str]) -> dict[str, Any]:
        """Global 문서가 없는 검색 결과의 신선도 조회를 생략한다."""
        return {}

    async def fake_prag_006(contexts: list[Any]) -> list[Any]:
        """맥락화 단계를 통과시킨다."""
        return contexts

    async def fake_expansion(connection: Any, **kwargs: Any) -> Any:
        """기존 반응형 1홉 검색이 호출됐음을 기록하고 이웃 키워드를 돌려준다."""
        expansion_calls.append(kwargs["topic"])
        return SimpleNamespace(
            keywords=("환헤지",),
            mode="verified_one_hop",
            gate_passed=True,
            maturity_reasons=(),
        )

    def fake_collect(topic: str, user_id: str, **kwargs: Any) -> list[Any]:
        """실시간 수집에 반응형 이웃 키워드가 전달되는지 기록한다."""
        collected_with.extend(kwargs["related_keywords"])
        return []

    def fake_generate(**kwargs: Any) -> str:
        """생성 입력을 고정 콘텐츠로 대체한다."""
        return "generated"

    async def fake_persist(connection: Any, **kwargs: Any) -> dict[str, object]:
        """저장 결과를 고정한다."""
        return {"content_candidate_id": "candidate-1"}

    monkeypatch.setattr(agent_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(agent_graph, "load_pinned_wiki_context", fake_pinned_context)
    monkeypatch.setattr(agent_graph, "prag_003", fake_prag_003)
    monkeypatch.setattr(agent_graph, "load_global_document_freshness", fake_freshness)
    monkeypatch.setattr(agent_graph, "prag_006", fake_prag_006)
    monkeypatch.setattr(
        agent_graph, "_load_related_keyword_expansion", fake_expansion
    )
    monkeypatch.setattr(agent_graph, "collect_live_context", fake_collect)
    monkeypatch.setattr(
        agent_graph, "generate_report_content_with_quality", fake_generate
    )
    monkeypatch.setattr(agent_graph, "prag_007", fake_persist)
    _disable_research(monkeypatch)

    asyncio.run(
        agent_graph.run_report_generation(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            attempt_number=1,
            topic="환율",
            content_type="interest_news_card",
            language="ko",
            # 매칭된 주제("코스피")가 있어도 이 요청의 주제("환율")와 다르면 쓰지 않는다.
            topic_interest_bundles={"코스피": {"keywords": ["코스피"]}},
        )
    )

    assert searched == ["환율"]
    assert expansion_calls == ["환율"]
    assert collected_with == ["환헤지"]
