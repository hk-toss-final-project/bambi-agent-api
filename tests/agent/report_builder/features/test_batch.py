"""비긴급 Report OpenAI Batch 등록과 결과 저장 경계를 검증한다."""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from agent.report_builder.features import batch as report_batch
from infrastructure.persistence.api import (
    ClaimedBatchResultItem,
    StoredLlmBatchItem,
)
from shared.report_models import ReportContextDocument


class _Connection:
    """빈 Transaction 문맥을 제공하는 연결 대역."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """도메인 저장 Transaction을 흉내 낸다."""
        yield


def _context() -> ReportContextDocument:
    """Report Batch 테스트용 개인 Wiki 근거를 만든다."""
    return ReportContextDocument(
        reference="P1",
        document_version_id="version-1",
        chunk_id="chunk-1",
        namespace_key="user/user-1",
        title="근거 제목",
        content="검증된 개인 지식 근거입니다.",
        url=None,
        score=0.9,
    )


def test_stage_report_generation_batch_freezes_prompt_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """명시적 Batch 요청이 Chat JSONL Body와 검색 Context Snapshot을 함께 저장한다."""
    captured: dict[str, Any] = {}

    async def fake_enqueue(connection: object, command: object) -> StoredLlmBatchItem:
        """등록 명령을 기록하고 고정 Item을 반환한다."""
        captured["command"] = command
        return StoredLlmBatchItem(
            item_id="item-1",
            custom_id=command.custom_id,  # type: ignore[attr-defined]
            status="queued",
            batch_id=None,
        )

    monkeypatch.setattr(report_batch, "enqueue_llm_batch_item", fake_enqueue)

    stored = asyncio.run(
        report_batch.stage_report_generation_batch(
            object(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="00000000-0000-0000-0000-000000000001",
            attempt_number=1,
            topic="AI 에이전트",
            content_type="interest_news_card",
            language="ko",
            contexts=[_context()],
            model="gpt-4.1-mini",
        )
    )

    command = captured["command"]
    assert stored.item_id == "item-1"
    assert command.endpoint == "/v1/chat/completions"
    assert command.workload == "report_generation"
    assert command.request_body["messages"][0]["role"] == "system"
    assert command.context["allowed_references"] == ["P1"]
    assert command.context["contexts"][0]["chunk_id"] == "chunk-1"


def test_apply_report_generation_batch_result_reuses_existing_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch 초안을 Citation 검증 후 기존 후보·Snapshot·Outbox 저장 경계에 전달한다."""
    persisted: dict[str, Any] = {}
    completed: dict[str, Any] = {}

    async def fake_scope(connection: object, *, user_id: str) -> None:
        """사용자 Scope를 검증한다."""
        assert user_id == "user-1"

    async def fake_persist(connection: object, **kwargs: Any) -> dict[str, object]:
        """기존 Report 저장 인자를 기록하고 결과를 반환한다."""
        persisted.update(kwargs)
        return {"content_id": "report-job-1", "version": 1}

    async def fake_complete(connection: object, **kwargs: Any) -> None:
        """waiting_provider Job 완료 인자를 기록한다."""
        completed.update(kwargs)

    monkeypatch.setattr(report_batch, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(report_batch, "persist_report_generation", fake_persist)
    monkeypatch.setattr(report_batch, "complete_waiting_provider_job", fake_complete)
    monkeypatch.setattr(
        report_batch.quality,
        "evaluate_report",
        lambda *args, **kwargs: SimpleNamespace(
            should_regenerate=False,
            correction="",
            reason="통과",
        ),
    )
    context = _context()
    item = ClaimedBatchResultItem(
        item_id="item-1",
        custom_id="report:1",
        user_id="user-1",
        job_id="00000000-0000-0000-0000-000000000001",
        workload="report_generation",
        model_name="gpt-4.1-mini",
        resource_type="generation_request",
        resource_id="job-1",
        context={
            "topic": "AI 에이전트",
            "topics": [],
            "content_type": "interest_news_card",
            "language": "ko",
            "allowed_references": ["P1"],
            "contexts": [
                {
                    "reference": context.reference,
                    "document_version_id": context.document_version_id,
                    "chunk_id": context.chunk_id,
                    "namespace_key": context.namespace_key,
                    "title": context.title,
                    "content": context.content,
                    "url": context.url,
                    "score": context.score,
                }
            ],
            "attempt_number": 1,
        },
        result_body={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"title":"제목","summary":"요약",'
                            '"body":"근거 본문 [P1]","citation_refs":["P1"]}'
                        )
                    }
                }
            ]
        },
    )

    result = asyncio.run(
        report_batch.apply_report_generation_batch_result(
            _Connection(),  # type: ignore[arg-type]
            item,
        )
    )

    assert result["content_id"] == "report-job-1"
    assert persisted["generated"].citation_references == ("P1",)
    assert persisted["contexts"][0].chunk_id == "chunk-1"
    assert completed["job_id"] == item.job_id
