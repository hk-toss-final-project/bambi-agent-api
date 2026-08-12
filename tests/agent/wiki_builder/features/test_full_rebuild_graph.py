"""Personal Wiki V3 전체 재구성 내부 LangGraph와 원자 교체를 검증한다."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from agent.wiki_builder.features import full_rebuild_graph
from agent.wiki_builder.features.full_rebuild_graph import (
    build_wiki_full_rebuild_graph_v3,
    run_wiki_full_rebuild_graph_v3,
)
from infrastructure.persistence.api import (
    PersistedWikiBuild,
    PersistedWikiDocument,
    UserSourceDocumentForAgent,
)
from shared.wiki_models import ConceptClassification, WikiClassification


class _Connection:
    """재구성 조회·원자 저장 Transaction 횟수를 기록하는 연결 대역."""

    def __init__(self) -> None:
        """Transaction 횟수를 0으로 초기화한다."""
        self.transactions = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """진입 횟수만 기록하는 빈 비동기 Transaction을 제공한다."""
        self.transactions += 1
        yield


def _source(index: int) -> UserSourceDocumentForAgent:
    """순차 전체 재구성에 사용할 활성 원본 Version을 만든다."""
    return UserSourceDocumentForAgent(
        source_document_id=f"source-{index}",
        source_document_version_id=f"source-version-{index}",
        source_event_id=f"event-{index}",
        user_id="user-1",
        namespace_key="user/user-1",
        source_type="web_clipping",
        canonical_url=f"https://example.com/{index}",
        version=1,
        title=f"주제 {index}",
        author=None,
        published_at=None,
        clipped_on=None,
        description=None,
        tags=["topic"],
        raw_content=f"주제 {index}의 원문입니다.",
        content_hash=str(index) * 64,
    )


def test_full_rebuild_v3_graph_exposes_every_internal_stage() -> None:
    """재구성 내부 분류·identity·관계·계획·원자 저장이 각각 노드로 드러난다."""
    assert set(build_wiki_full_rebuild_graph_v3().get_graph().nodes) == {
        "__start__",
        "load_manifest",
        "select_source",
        "resolve_onboarding_context",
        "classify_source",
        "prepare_identity",
        "resolve_identity",
        "validate_identity",
        "recall_relations",
        "link_relations",
        "plan_source",
        "accumulate_source",
        "validate_snapshot",
        "atomic_persist",
        "embed",
        "retire_without_sources",
        "finalize",
        "__end__",
    }


def test_full_rebuild_v3_processes_sources_sequentially_then_commits_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """원본별 LLM 계획을 순차 누적한 뒤 저장은 하나의 Transaction에서 실행한다."""
    connection = _Connection()
    classifications: list[str] = []
    persisted_titles: list[str] = []
    summary: dict[str, Any] = {}
    embedded: dict[str, Any] = {}

    async def fake_scope(*args: Any, **kwargs: Any) -> None:
        """테스트에서 실제 RLS SQL을 생략한다."""

    async def fake_sources(*args: Any, **kwargs: Any) -> list[UserSourceDocumentForAgent]:
        """고정 순서의 활성 원본 두 건을 반환한다."""
        return [_source(1), _source(2)]

    def fake_classifier(**kwargs: Any) -> WikiClassification:
        """원본 제목마다 서로 다른 Concept 한 건을 분류한다."""
        title = str(kwargs["source_title"])
        classifications.append(title)
        return WikiClassification(
            source_summary=f"{title} 요약",
            concepts=[
                ConceptClassification(
                    title=title,
                    definition=f"{title} 정의",
                    role="subject",
                )
            ],
        )

    def fake_linker(**kwargs: Any) -> WikiClassification:
        """관계 후보가 없는 테스트 분류를 그대로 반환한다."""
        return kwargs["classification"]

    async def fake_save_contexts(*args: Any, **kwargs: Any) -> int:
        """생성된 온보딩 Context가 없음을 반환한다."""
        return 0

    async def fake_supersede(*args: Any, **kwargs: Any) -> int:
        """원자 교체에서 기존 문서 두 건을 내렸다고 반환한다."""
        return 2

    async def fake_persist(*args: Any, **kwargs: Any) -> PersistedWikiBuild:
        """원본별 계획을 저장 결과 값 객체로 변환한다."""
        plan = kwargs["plan"]
        source = kwargs["source"]
        persisted_titles.append(source.title)
        documents = [*plan.entities, *plan.concepts, plan.schema]
        return PersistedWikiBuild(
            wiki_version_id="wiki-v3",
            wiki_version=3,
            affected_documents=[
                PersistedWikiDocument(
                    document_id=f"{document.document_kind}:{document.document_key}",
                    document_version_id=(
                        f"version:{source.source_document_version_id}:"
                        f"{document.document_kind}:{document.document_key}"
                    ),
                    document_kind=document.document_kind,
                    document_key=document.document_key,
                    file_path=document.file_path,
                    version=1,
                    action=document.action,
                )
                for document in documents
            ],
            chunk_count=4,
            stored_relation_count=0,
        )

    async def fake_summary(*args: Any, **kwargs: Any) -> None:
        """최종 Snapshot 요약 인자를 기록한다."""
        summary.update(kwargs)

    async def fake_embed(*args: Any, **kwargs: Any) -> int:
        """최종 변경 Page Version과 모델을 기록한다."""
        embedded.update(kwargs)
        return len(kwargs["document_version_ids"])

    monkeypatch.setattr(full_rebuild_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        full_rebuild_graph,
        "list_user_source_versions_for_rebuild",
        fake_sources,
    )
    monkeypatch.setattr(full_rebuild_graph, "save_custom_topic_contexts", fake_save_contexts)
    monkeypatch.setattr(
        full_rebuild_graph,
        "supersede_personal_wiki_for_rebuild",
        fake_supersede,
    )
    monkeypatch.setattr(full_rebuild_graph, "persist_wiki_build", fake_persist)
    monkeypatch.setattr(full_rebuild_graph, "update_full_wiki_rebuild_summary", fake_summary)
    monkeypatch.setattr(full_rebuild_graph, "wba_011", fake_embed)

    result = asyncio.run(
        run_wiki_full_rebuild_graph_v3(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            model="model-test",
            embedding_model="embedding-test",
            classifier=fake_classifier,
            linker=fake_linker,
            generated_at="2026-08-12T00:00:00+00:00",
        )
    )

    assert classifications == ["주제 1", "주제 2"]
    assert persisted_titles == ["주제 1", "주제 2"]
    assert connection.transactions == 2
    assert summary["source_count"] == 2
    assert summary["superseded_document_count"] == 2
    assert embedded["model"] == "embedding-test"
    assert len(embedded["document_version_ids"]) == 2
    assert result["full_rebuild_pipeline_version"] == "langgraph_v3"
    assert result["source_count"] == 2
    assert result["wiki_version_id"] == "wiki-v3"


def test_full_rebuild_v3_retires_derivatives_when_no_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """활성 원본이 없으면 LLM 없이 기존 Wiki와 검색 파생물을 retire한다."""
    connection = _Connection()
    retired: list[str] = []

    async def fake_scope(*args: Any, **kwargs: Any) -> None:
        """테스트에서 실제 RLS SQL을 생략한다."""

    async def no_sources(*args: Any, **kwargs: Any) -> list[UserSourceDocumentForAgent]:
        """빈 활성 원본 manifest를 반환한다."""
        return []

    async def fake_retire(*args: Any, **kwargs: Any) -> dict[str, int]:
        """retire 호출 사용자를 기록하고 집계를 반환한다."""
        retired.append(kwargs["user_id"])
        return {
            "superseded_document_count": 3,
            "unsearchable_chunk_count": 7,
        }

    def unexpected(*args: Any, **kwargs: Any) -> WikiClassification:
        """무원본 경로에서 LLM 분류가 호출되면 실패한다."""
        raise AssertionError("활성 원본 없이 분류하면 안 됩니다.")

    monkeypatch.setattr(full_rebuild_graph, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        full_rebuild_graph,
        "list_user_source_versions_for_rebuild",
        no_sources,
    )
    monkeypatch.setattr(
        full_rebuild_graph,
        "retire_personal_wiki_without_sources",
        fake_retire,
    )

    result = asyncio.run(
        run_wiki_full_rebuild_graph_v3(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            classifier=unexpected,
            linker=unexpected,
        )
    )

    assert retired == ["user-1"]
    assert connection.transactions == 2
    assert result["wiki_version_id"] is None
    assert result["source_count"] == 0
    assert result["unsearchable_chunk_count"] == 7
