"""WBA-001 증분 Wiki Build의 계층 조정을 검증한다."""

import asyncio
from dataclasses import replace
from datetime import date
from typing import Any

from pytest import MonkeyPatch

from agent.wiki_builder.features import orchestration
from agent.wiki_builder.models import (
    ConceptClassification,
    EntityClassification,
    WikiClassification,
    WikiNodeDisposition,
    WikiRelationClassification,
)
from infrastructure.persistence.features.jobs import CompletedAgentJobAnchor
from infrastructure.persistence.features.personal_wiki import (
    PersistedWikiBuild,
    PersistedWikiDocument,
    UserSourceDocumentForAgent,
)


class _Transaction:
    """Transaction 진입·종료를 표현하는 비동기 Context Manager."""

    async def __aenter__(self) -> None:
        """Transaction 진입을 허용한다."""
        return None

    async def __aexit__(self, *args: object) -> None:
        """Transaction 종료를 허용한다."""
        return None


class _FakeConnection:
    """Transaction 횟수만 기록하는 Connection Test Double."""

    def __init__(self) -> None:
        self.transaction_count = 0

    def transaction(self) -> _Transaction:
        """새 Transaction Context를 반환한다."""
        self.transaction_count += 1
        return _Transaction()


def _source() -> UserSourceDocumentForAgent:
    """WBA-001 테스트용 클리핑 원본을 만든다."""
    return UserSourceDocumentForAgent(
        source_document_id="source-1",
        source_document_version_id="source-version-1",
        source_event_id="event-1",
        user_id="user-1",
        namespace_key="user/user-1",
        source_type="web_clipping",
        canonical_url="https://example.com/obsidian",
        version=1,
        title="Obsidian 소개",
        author=None,
        published_at=None,
        clipped_on=date(2026, 7, 15),
        description="지식 관리 도구 소개",
        tags=["clippings", "pkm"],
        raw_content="Obsidian은 Markdown 기반 도구다.",
        content_format="markdown",
        content_hash="a" * 64,
    )


def _onboarding_source() -> UserSourceDocumentForAgent:
    """온보딩 결정적 분류 테스트용 합성 원본을 만든다."""
    return UserSourceDocumentForAgent(
        source_document_id="source-onboarding",
        source_document_version_id="source-version-onboarding",
        source_event_id="event-onboarding",
        user_id="user-onboarding",
        namespace_key="user/user-onboarding",
        source_type="onboarding_seed",
        canonical_url=None,
        version=1,
        title="온보딩 관심 주제 시드",
        author=None,
        published_at=None,
        clipped_on=date(2026, 8, 5),
        description="온보딩 선택 관심 주제",
        tags=[],
        raw_content="# 온보딩 관심 주제 시드\n\nAI·머신러닝, 반도체",
        content_format="markdown",
        content_hash="b" * 64,
        source_metadata={
            "labels": ["AI·머신러닝", "반도체", "AI·머신러닝", " "],
        },
    )


def test_build_incremental_wiki_closes_read_transaction_before_llm(
    monkeypatch: MonkeyPatch,
) -> None:
    """DB 조회·LLM 호출·DB 저장을 분리된 경계로 실행한다."""
    connection = _FakeConnection()
    captured: dict[str, Any] = {}

    async def fake_scope(connection: object, *, user_id: str) -> None:
        """RLS Scope 설정 호출을 기록한다."""
        captured.setdefault("scopes", []).append(user_id)

    async def fake_source(connection: object, **kwargs: object) -> UserSourceDocumentForAgent:
        """고정된 클리핑 원본을 반환한다."""
        return _source()

    async def fake_existing(connection: object, **kwargs: object) -> list[object]:
        """빈 기존 Wiki 목록을 반환한다."""
        return []

    def fake_classifier(**kwargs: object) -> WikiClassification:
        """LLM 호출 시점의 Transaction 수와 입력을 기록한다."""
        captured["transactions_at_llm"] = connection.transaction_count
        captured["classifier"] = kwargs
        return WikiClassification(
            source_summary="Obsidian 요약",
            entities=[
                EntityClassification(
                    name="Obsidian",
                    subtype="product",
                    description="Markdown 기반 도구다.",
                )
            ],
        )

    def fake_linker(**kwargs: object) -> WikiClassification:
        """별도 관계 판정이 Transaction 밖에서 실행되는지 기록한다."""
        captured["transactions_at_linker"] = connection.transaction_count
        return kwargs["classification"]  # type: ignore[return-value]

    async def fake_embedding(connection: object, **kwargs: object) -> int:
        """외부 Embedding 호출 없이 갱신 건수를 반환한다."""
        return 1

    async def fake_persist(connection: object, **kwargs: object) -> PersistedWikiBuild:
        """고정된 Wiki Build 저장 결과를 반환한다."""
        captured["plan"] = kwargs["plan"]
        return PersistedWikiBuild(
            wiki_version_id="wiki-1",
            wiki_version=1,
            affected_documents=[
                PersistedWikiDocument(
                    document_id="doc-1",
                    document_version_id="version-1",
                    document_kind="entity",
                    document_key="obsidian",
                    file_path="entities/obsidian.md",
                    version=1,
                    action="create",
                )
            ],
            chunk_count=3,
        )

    monkeypatch.setattr(orchestration, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        orchestration, "get_user_source_document_version_for_agent", fake_source
    )
    monkeypatch.setattr(orchestration, "list_existing_wiki_entries", fake_existing)
    monkeypatch.setattr(orchestration, "list_existing_wiki_relations", fake_existing)
    monkeypatch.setattr(
        orchestration, "list_onboarding_wiki_anchor_keys", fake_existing
    )
    monkeypatch.setattr(orchestration, "list_wiki_node_embeddings", fake_existing)
    monkeypatch.setattr(orchestration, "link_wiki_relations", fake_linker)
    monkeypatch.setattr(orchestration, "wba_011", fake_embedding)
    monkeypatch.setattr(orchestration, "persist_wiki_build", fake_persist)

    persisted, plan = asyncio.run(
        orchestration.build_incremental_wiki(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_version_id="source-version-1",
            job_id="job-1",
            classifier=fake_classifier,
            generated_at="2026-07-15T12:00:00+09:00",
        )
    )

    assert captured["transactions_at_llm"] == 1
    assert captured["transactions_at_linker"] == 1
    assert connection.transaction_count == 2
    assert captured["scopes"] == ["user-1", "user-1"]
    assert captured["classifier"]["source_tags"] == ["clippings", "pkm"]
    assert persisted.wiki_version_id == "wiki-1"
    assert plan.entities[0].document_key == "obsidian"


def test_build_incremental_wiki_materializes_onboarding_labels_without_llm(
    monkeypatch: MonkeyPatch,
) -> None:
    """온보딩 선택 라벨만 Concept로 만들고 합성 문서 제목은 노드에서 제외한다."""
    connection = _FakeConnection()
    captured: dict[str, Any] = {}

    async def fake_scope(connection: object, *, user_id: str) -> None:
        """RLS Scope 설정 호출을 기록한다."""
        captured.setdefault("scopes", []).append(user_id)

    async def fake_source(connection: object, **kwargs: object) -> UserSourceDocumentForAgent:
        """온보딩 합성 원본을 반환한다."""
        return _onboarding_source()

    async def fake_existing(connection: object, **kwargs: object) -> list[object]:
        """빈 기존 Wiki 목록을 반환한다."""
        return []

    def fail_if_llm_is_called(**kwargs: object) -> WikiClassification:
        """온보딩 시드에서 LLM 분류가 실행되면 테스트를 실패시킨다."""
        raise AssertionError("온보딩 시드는 LLM 분류기를 호출하면 안 됩니다.")

    async def fake_persist(connection: object, **kwargs: object) -> PersistedWikiBuild:
        """Wiki Build 계획을 기록하고 고정된 저장 결과를 반환한다."""
        captured["plan"] = kwargs["plan"]
        return PersistedWikiBuild(
            wiki_version_id="wiki-onboarding",
            wiki_version=1,
            affected_documents=[],
            chunk_count=0,
        )

    monkeypatch.setattr(orchestration, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        orchestration, "get_user_source_document_version_for_agent", fake_source
    )
    monkeypatch.setattr(orchestration, "list_existing_wiki_entries", fake_existing)
    monkeypatch.setattr(orchestration, "list_existing_wiki_relations", fake_existing)
    monkeypatch.setattr(
        orchestration, "list_onboarding_wiki_anchor_keys", fake_existing
    )
    monkeypatch.setattr(orchestration, "list_wiki_node_embeddings", fake_existing)
    monkeypatch.setattr(orchestration, "persist_wiki_build", fake_persist)

    persisted, plan = asyncio.run(
        orchestration.build_incremental_wiki(
            connection,  # type: ignore[arg-type]
            user_id="user-onboarding",
            source_document_version_id="source-version-onboarding",
            job_id="job-onboarding",
            classifier=fail_if_llm_is_called,
            generated_at="2026-08-05T12:00:00+09:00",
        )
    )

    assert persisted.wiki_version_id == "wiki-onboarding"
    assert [concept.title for concept in plan.concepts] == ["AI·머신러닝", "반도체"]
    assert len({concept.normalized_content for concept in plan.concepts}) == 2
    assert plan.entities == []
    assert all(concept.title not in {"온보딩", "온보딩 관심 주제 시드"} for concept in plan.concepts)
    assert connection.transaction_count == 2
    assert captured["scopes"] == ["user-onboarding", "user-onboarding"]


def test_rebuild_full_wiki_stages_all_llm_work_before_atomic_replacement(
    monkeypatch: MonkeyPatch,
) -> None:
    """전체 원본 계획과 Lint가 끝난 후 하나의 Transaction에서 Wiki를 교체한다."""
    connection = _FakeConnection()
    events: list[str] = []
    onboarding = _onboarding_source()
    article = replace(
        _source(),
        title="폭염 기사",
        raw_content="서울에 38도 폭염이 이어졌다.",
    )

    async def fake_scope(_connection: object, *, user_id: str) -> None:
        """테스트에서 RLS 설정을 기록한다."""
        events.append(f"scope:{user_id}")

    async def fake_sources(_connection: object, *, user_id: str) -> list[object]:
        """온보딩과 클리핑 현재 Version을 반환한다."""
        return [onboarding, article]

    def fake_classifier(**kwargs: object) -> WikiClassification:
        """클리핑에서 폭염 Concept을 추출한다."""
        events.append("classify:heatwave")
        assert connection.transaction_count == 1
        return WikiClassification(
            source_summary="폭염",
            concepts=[
                ConceptClassification(
                    title="폭염",
                    subtype="phenomenon",
                    definition="매우 심한 더위",
                )
            ],
        )

    def fake_linker(**kwargs: object) -> WikiClassification:
        """폭염을 온보딩 날씨 anchor에 연결한다."""
        events.append("link:weather")
        classification = kwargs["classification"]
        return WikiClassification(
            source_summary=classification.source_summary,  # type: ignore[union-attr]
            concepts=classification.concepts,  # type: ignore[union-attr]
            relations=[
                WikiRelationClassification(
                    source_name="폭염",
                    source_kind="concept",
                    target_name="날씨",
                    target_kind="concept",
                    target_matched_key="날씨",
                    relation_type="subtopic_of",
                    evidence="서울에 38도 폭염이 이어졌다.",
                    provenance_kind="semantic_inference",
                    confidence=0.86,
                    review_status="accepted",
                    rationale="폭염은 날씨의 세부 현상",
                )
            ],
            node_dispositions=[
                WikiNodeDisposition(
                    node_name="폭염",
                    node_kind="concept",
                    disposition="connect",
                    reason="날씨 하위 주제",
                )
            ],
        )

    async def fake_supersede(
        _connection: object, *, user_id: str, job_id: str
    ) -> int:
        """최종 Transaction에서만 기존 Wiki를 대체한다."""
        events.append("supersede")
        assert connection.transaction_count == 2
        assert job_id == "rebuild-job"
        return 5

    async def fake_persist(
        _connection: object, *, source: object, plan: object, job_id: str
    ) -> PersistedWikiBuild:
        """원본별 스테이징 계획을 같은 Transaction에 저장한다."""
        events.append(f"persist:{source.source_type}")  # type: ignore[union-attr]
        key = f"version-{len(events)}"
        documents = []
        if plan.concepts:  # type: ignore[union-attr]
            document = plan.concepts[0]  # type: ignore[union-attr]
            documents.append(
                PersistedWikiDocument(
                    document_id=f"doc-{key}",
                    document_version_id=key,
                    document_kind="concept",
                    document_key=document.document_key,
                    file_path=document.file_path,
                    version=1,
                    action="create",
                )
            )
        return PersistedWikiBuild(
            wiki_version_id="wiki-rebuild",
            wiki_version=2,
            affected_documents=documents,
            chunk_count=len(documents),
        )

    async def fake_embedding(_connection: object, **kwargs: object) -> int:
        """스테이징 문서 Vector 갱신 건수를 반환한다."""
        events.append("embed")
        return len(kwargs["document_version_ids"])  # type: ignore[arg-type]

    async def fake_summary(_connection: object, **kwargs: object) -> None:
        """최종 Wiki Version 요약이 전체 원본 범위를 기록하는지 검증한다."""
        events.append("summary")
        assert kwargs == {
            "user_id": "user-onboarding",
            "wiki_version_id": "wiki-rebuild",
            "source_count": 2,
            "affected_document_count": 2,
            "superseded_document_count": 5,
        }

    monkeypatch.setattr(orchestration, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        orchestration, "list_user_source_versions_for_rebuild", fake_sources
    )
    monkeypatch.setattr(
        orchestration, "supersede_personal_wiki_for_rebuild", fake_supersede
    )
    monkeypatch.setattr(orchestration, "persist_wiki_build", fake_persist)
    monkeypatch.setattr(
        orchestration,
        "update_full_wiki_rebuild_summary",
        fake_summary,
    )
    monkeypatch.setattr(orchestration, "wba_011", fake_embedding)

    result = asyncio.run(
        orchestration.rebuild_full_wiki(
            connection,  # type: ignore[arg-type]
            user_id="user-onboarding",
            job_id="rebuild-job",
            classifier=fake_classifier,
            linker=fake_linker,
            generated_at="2026-08-07T12:00:00+09:00",
        )
    )

    assert events.index("classify:heatwave") < events.index("supersede")
    assert events.index("link:weather") < events.index("supersede")
    assert events[-5:] == [
        "supersede",
        "persist:onboarding_seed",
        "persist:web_clipping",
        "summary",
        "embed",
    ]
    assert connection.transaction_count == 2
    assert result.source_count == 2
    assert result.superseded_document_count == 5
    assert result.quality.passed is True
    assert result.embedding_count == 2


def test_wba_018_persists_claude_classification_without_source_llm_call(
    monkeypatch: MonkeyPatch,
) -> None:
    """Claude 분류 결과가 원문 분류·관계 Linker LLM 호출 없이 저장되는지 검증한다."""
    connection = _FakeConnection()
    captured: dict[str, Any] = {}

    async def fake_scope(_connection: object, *, user_id: str) -> None:
        """RLS Scope 설정 호출을 기록한다."""
        captured.setdefault("scopes", []).append(user_id)

    async def fake_source(_connection: object, **kwargs: object) -> UserSourceDocumentForAgent:
        """고정된 클리핑 원본을 반환한다."""
        return _source()

    async def fake_existing(_connection: object, **kwargs: object) -> list[object]:
        """빈 기존 Wiki 목록을 반환한다."""
        return []

    async def fake_job(_connection: object, **kwargs: object) -> CompletedAgentJobAnchor:
        """즉시 완료 처리된 Job 식별자를 기록하고 반환한다."""
        captured["job_kwargs"] = kwargs
        return CompletedAgentJobAnchor(job_id="job-mcp-write-1")

    async def fake_persist(_connection: object, **kwargs: object) -> PersistedWikiBuild:
        """전달된 Job ID와 계획을 기록하고 고정된 저장 결과를 반환한다."""
        captured["persist_job_id"] = kwargs["job_id"]
        captured["plan"] = kwargs["plan"]
        return PersistedWikiBuild(
            wiki_version_id="wiki-claude-1",
            wiki_version=1,
            affected_documents=[
                PersistedWikiDocument(
                    document_id="doc-1",
                    document_version_id="version-1",
                    document_kind="entity",
                    document_key="obsidian",
                    file_path="entities/obsidian.md",
                    version=1,
                    action="create",
                )
            ],
            chunk_count=1,
        )

    async def fake_embedding(_connection: object, **kwargs: object) -> int:
        """재임베딩 호출 인자를 기록한다."""
        captured["embedding_kwargs"] = kwargs
        return 1

    monkeypatch.setattr(orchestration, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        orchestration, "get_user_source_document_version_for_agent", fake_source
    )
    monkeypatch.setattr(orchestration, "list_existing_wiki_entries", fake_existing)
    monkeypatch.setattr(orchestration, "list_existing_wiki_relations", fake_existing)
    monkeypatch.setattr(orchestration, "create_completed_agent_job", fake_job)
    monkeypatch.setattr(orchestration, "persist_wiki_build", fake_persist)
    monkeypatch.setattr(orchestration, "wba_011", fake_embedding)

    classification = WikiClassification(
        source_summary="Claude가 요약한 내용",
        entities=[
            EntityClassification(
                name="Obsidian",
                subtype="product",
                description="Claude가 정리한 설명",
            )
        ],
        concepts=[
            ConceptClassification(
                title="PKM",
                subtype="method",
                definition="Claude가 정리한 정의",
            )
        ],
    )

    persisted, quality = asyncio.run(
        orchestration.wba_018(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            source_document_version_id="source-version-1",
            classification=classification,
        )
    )

    assert persisted.wiki_version_id == "wiki-claude-1"
    assert quality.passed is True
    assert captured["persist_job_id"] == "job-mcp-write-1"
    assert captured["job_kwargs"]["feature_id"] == "WBA-018"
    assert captured["job_kwargs"]["job_type"] == "personal_wiki_mcp_write"
    assert captured["plan"].entities[0].document_key == "obsidian"
    assert captured["plan"].concepts[0].document_key == "pkm"
    assert captured["embedding_kwargs"]["document_version_ids"] == ["version-1"]
    assert connection.transaction_count == 2


def test_wba_018_rejects_missing_source_document_version_id() -> None:
    """source_document_version_id가 비어 있으면 저장을 시도하지 않고 거부한다."""
    connection = _FakeConnection()

    try:
        asyncio.run(
            orchestration.wba_018(
                connection,  # type: ignore[arg-type]
                user_id="user-1",
                source_document_version_id="",
                classification=WikiClassification(),
            )
        )
    except ValueError:
        pass
    else:
        raise AssertionError("빈 source_document_version_id는 거부되어야 합니다.")
    assert connection.transaction_count == 0


def test_combine_rebuild_results_keeps_only_latest_document_version() -> None:
    """여러 원본이 같은 노드를 갱신해도 최종 Version만 재임베딩 대상으로 남긴다."""
    first_document = PersistedWikiDocument(
        document_id="weather",
        document_version_id="weather-v1",
        document_kind="concept",
        document_key="weather",
        file_path="concepts/weather.md",
        version=1,
        action="create",
    )
    latest_document = replace(
        first_document,
        document_version_id="weather-v2",
        version=2,
        action="update",
    )
    first = PersistedWikiBuild(
        wiki_version_id="wiki",
        wiki_version=1,
        affected_documents=[first_document],
        chunk_count=1,
        superseded_relation_count=2,
    )
    latest = PersistedWikiBuild(
        wiki_version_id="wiki",
        wiki_version=1,
        affected_documents=[latest_document],
        chunk_count=1,
        superseded_relation_count=3,
    )

    combined = orchestration._combine_rebuild_results([first, latest])

    assert combined.affected_documents == [latest_document]
    assert combined.superseded_relation_count == 5
