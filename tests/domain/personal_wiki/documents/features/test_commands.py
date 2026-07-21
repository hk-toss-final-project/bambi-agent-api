"""개인 Wiki 문서 명령 facade 구현을 검증한다."""

import asyncio
from datetime import date
from types import SimpleNamespace
from typing import Any

from pytest import MonkeyPatch

from domain.personal_wiki.documents.features import commands
from infrastructure.persistence.api import UserSourceDocumentForAgent
from shared.contracts import FeatureRequest
from shared.wiki_models import GeneratedArtifact, WikiBuildPlan, WikiDocumentPlan


class _FakeConnection:
    """execute 메서드만 제공하는 DB Connection 대역."""

    async def execute(self, *args: object, **kwargs: object) -> None:
        """테스트에서 호출되지 않는 실행 메서드를 제공한다."""
        return None


def _source() -> UserSourceDocumentForAgent:
    """PWIKI-002 테스트용 사용자 원본 Version을 만든다."""
    return UserSourceDocumentForAgent(
        source_document_id="source-1",
        source_document_version_id="source-version-1",
        source_event_id="event-1",
        user_id="user-1",
        namespace_key="user/user-1",
        source_type="web_clipping",
        canonical_url="https://example.com",
        version=1,
        title="원본",
        author=None,
        published_at=None,
        clipped_on=date(2026, 7, 21),
        description=None,
        raw_content="# 원본",
    )


def _plan() -> WikiBuildPlan:
    """PWIKI-002 테스트용 최소 Wiki Build 계획을 만든다."""
    schema = WikiDocumentPlan(
        document_kind="schema",
        document_key="schema",
        file_path="schema/schema.md",
        domain=None,
        title="Schema",
        summary="요약",
        normalized_content="# Schema",
        action="update",
    )
    artifact = GeneratedArtifact(file_path="artifact.md", content="# Artifact")
    return WikiBuildPlan(
        entities=[],
        concepts=[],
        schema=schema,
        relations=[],
        index=artifact,
        source_manifest=artifact,
        log_entry=artifact,
    )


def test_pwiki_002_delegates_to_persistence_facade(
    monkeypatch: MonkeyPatch,
) -> None:
    """PWIKI-002가 검증된 입력으로 기존 Wiki 저장 구현을 호출한다."""
    connection = _FakeConnection()
    source = _source()
    plan = _plan()
    persisted = SimpleNamespace(wiki_version_id="wiki-version-1")
    captured: dict[str, Any] = {}

    async def fake_persist(connection_value: object, **kwargs: object) -> object:
        """저장 호출 인자를 기록하고 고정 결과를 반환한다."""
        captured["connection"] = connection_value
        captured.update(kwargs)
        return persisted

    monkeypatch.setattr(commands, "persist_wiki_build", fake_persist)
    result = asyncio.run(
        commands.pwiki_002(
            FeatureRequest(
                request_id="request-1",
                user_id="user-1",
                payload={
                    "connection": connection,
                    "source": source,
                    "plan": plan,
                    "job_id": "job-1",
                },
            )
        )
    )

    assert result.feature_id == "PWIKI-002"
    assert result.data["persisted"] is persisted
    assert captured == {
        "connection": connection,
        "source": source,
        "plan": plan,
        "job_id": "job-1",
    }
