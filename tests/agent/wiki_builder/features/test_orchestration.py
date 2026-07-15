"""WBA-001 증분 Wiki Build의 계층 조정을 검증한다."""

import asyncio
from datetime import date
from typing import Any

from pytest import MonkeyPatch

from agent.wiki_builder.features import orchestration
from agent.wiki_builder.models import EntityClassification, WikiClassification
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
    assert connection.transaction_count == 2
    assert captured["scopes"] == ["user-1", "user-1"]
    assert captured["classifier"]["source_tags"] == ["clippings", "pkm"]
    assert persisted.wiki_version_id == "wiki-1"
    assert plan.entities[0].document_key == "obsidian"
