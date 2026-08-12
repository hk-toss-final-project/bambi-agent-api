"""아침 브리핑 준비 Worker의 V2 근거 예열과 멱등 실행을 검증한다."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from agent.report_builder.api import ReportContextDocument
from app.schemas.briefing_topics import BriefingTopicsResponse
from infrastructure.persistence.api import ClaimedAgentJob, StoredBriefingTopicSnapshot
from workers.features import briefing_preparation


class _FakeConnection:
    """완료 처리에 필요한 빈 Transaction 문맥을 제공한다."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """빈 비동기 Transaction 문맥을 제공한다."""
        yield


def _context(reference: str, namespace: str) -> ReportContextDocument:
    """근거 병합 검증에 사용할 문서 하나를 만든다."""
    return ReportContextDocument(
        reference=reference,
        document_version_id=f"version-{reference}",
        chunk_id=f"chunk-{reference}",
        namespace_key=namespace,
        title=f"제목 {reference}",
        content=f"본문 {reference}",
        url=None,
        score=0.9,
    )


def _job(payload: dict[str, object]) -> ClaimedAgentJob:
    """점유된 브리핑 준비 Job을 만든다."""
    return ClaimedAgentJob(
        job_id="job-1",
        user_id="user-1",
        feature_id="REPORT-022",
        job_type="briefing_preparation",
        attempt_number=1,
        max_attempts=3,
        payload=payload,
    )


def test_collect_prepared_contexts_runs_v2_and_only_missing_live_topics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """모든 Topic은 V2 저장 근거를 읽고 부족한 Topic만 Live로 보강한다."""
    read_calls: list[tuple[str, bool, str | None]] = []
    live_calls: list[str] = []

    async def fake_read(
        connection: Any, *, topic: str, defer_live: bool, **kwargs: Any
    ) -> Any:
        """Topic별 V2 결과와 Live 필요 여부를 반환한다."""
        read_calls.append((topic, defer_live, kwargs.get("job_id")))
        return SimpleNamespace(
            documents=(_context("P1", "user/user-1"),),
            requires_live=topic == "반도체",
        )

    def fake_live(topic: str, user_id: str, *, model: str) -> list[Any]:
        """Live 호출 Topic을 기록하고 근거 하나를 반환한다."""
        live_calls.append(topic)
        return [_context("L1", "live")]

    monkeypatch.setattr(briefing_preparation, "run_wiki_read_graph_v2", fake_read)
    monkeypatch.setattr(briefing_preparation, "collect_live_context", fake_live)

    contexts = asyncio.run(
        briefing_preparation._collect_prepared_contexts(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            topics=["반도체", "프로야구"],
            model="report-model",
        )
    )

    assert read_calls == [("반도체", True, None), ("프로야구", True, None)]
    assert live_calls == ["반도체"]
    assert [item.namespace_key for item in contexts["반도체"]] == [
        "user/user-1",
        "live",
    ]
    assert len(contexts["프로야구"]) == 1


class _FakeService:
    """선정·저장 호출을 기록하는 브리핑 서비스 대역."""

    def __init__(self, existing: StoredBriefingTopicSnapshot | None = None) -> None:
        """선택적으로 기존 Snapshot을 보관한다."""
        self.existing = existing
        self.selected = 0
        self.saved = 0

    async def get_preparation_snapshot(
        self, user_id: str, *, briefing_date: date
    ) -> StoredBriefingTopicSnapshot | None:
        """기존 Snapshot을 반환한다."""
        return self.existing

    async def select_topics(
        self, user_id: str, *, limit: int
    ) -> BriefingTopicsResponse:
        """고정 주제를 선정한다."""
        self.selected += 1
        return BriefingTopicsResponse(
            user_id=user_id,
            topics=["반도체"],
            reason="테스트 선정",
            candidate_count=4,
        )

    async def save_preparation(self, user_id: str, **kwargs: Any) -> Any:
        """준비 결과를 Snapshot으로 변환해 반환한다."""
        self.saved += 1
        selection = kwargs["selection"]
        contexts = kwargs["contexts_by_topic"]
        return StoredBriefingTopicSnapshot(
            user_id=user_id,
            briefing_date=kwargs["briefing_date"],
            topics=tuple(selection.topics),
            reason=selection.reason,
            candidate_count=selection.candidate_count,
            contexts_by_topic={
                topic: [{"reference": item.reference} for item in items]
                for topic, items in contexts.items()
            },
            prepared_by_job_id=kwargs["prepared_by_job_id"],
            prepared_at=datetime(2026, 8, 11, tzinfo=UTC),
        )


def test_prepare_briefing_snapshot_selects_wiki_topics_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshot 미준비 상태는 Wiki 선정·근거 수집·저장을 한 번씩 수행한다."""
    service = _FakeService()

    async def fake_collect(*args: Any, **kwargs: Any) -> dict[str, list[Any]]:
        """선정 주제에 대응하는 고정 근거를 반환한다."""
        assert kwargs["topics"] == ["반도체"]
        return {"반도체": [_context("P1", "user/user-1")]}

    monkeypatch.setattr(briefing_preparation, "_collect_prepared_contexts", fake_collect)

    snapshot = asyncio.run(
        briefing_preparation.prepare_briefing_snapshot(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            briefing_date=date(2026, 8, 12),
            limit=3,
            prepared_by_job_id="report-job-1",
            model="report-model",
            service=service,  # type: ignore[arg-type]
        )
    )

    assert snapshot.topics == ("반도체",)
    assert service.selected == 1
    assert service.saved == 1


def test_process_job_reuses_existing_snapshot_without_llm_or_research(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """같은 사용자·날짜 재실행은 저장된 결과를 재사용해 외부 호출을 반복하지 않는다."""
    existing = StoredBriefingTopicSnapshot(
        user_id="user-1",
        briefing_date=date(2026, 8, 12),
        topics=("반도체",),
        reason="이미 준비됨",
        candidate_count=4,
        contexts_by_topic={"반도체": [{"reference": "P1"}]},
        prepared_by_job_id="old-job",
        prepared_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    service = _FakeService(existing)
    completed: list[Any] = []

    async def fail_collect(*args: Any, **kwargs: Any) -> Any:
        """재사용 경로에서 근거 수집이 호출되면 실패한다."""
        raise AssertionError("기존 Snapshot을 다시 조사하면 안 됩니다.")

    async def fake_complete(connection: Any, command: Any) -> None:
        """완료 Command를 기록한다."""
        completed.append(command)

    async def fake_scope(connection: Any) -> None:
        """테스트에서는 시스템 Scope 변경을 생략한다."""

    monkeypatch.setattr(briefing_preparation, "_collect_prepared_contexts", fail_collect)
    monkeypatch.setattr(briefing_preparation, "db_026", fake_complete)
    monkeypatch.setattr(briefing_preparation, "set_system_job_scope", fake_scope)

    result = asyncio.run(
        briefing_preparation._process_job(
            _FakeConnection(),  # type: ignore[arg-type]
            job=_job({"briefing_date": "2026-08-12", "limit": 3}),
            worker_id="worker-1",
            model="report-model",
            service=service,  # type: ignore[arg-type]
        )
    )

    assert result["topics"] == ["반도체"]
    assert service.selected == 0
    assert service.saved == 0
    assert len(completed) == 1


def test_process_job_rejects_invalid_briefing_date() -> None:
    """잘못된 날짜 Payload는 재시도 불가능한 입력 오류로 분류한다."""
    with pytest.raises(ValueError, match="briefing_date"):
        asyncio.run(
            briefing_preparation._process_job(
                _FakeConnection(),  # type: ignore[arg-type]
                job=_job({"briefing_date": "not-a-date", "limit": 3}),
                worker_id="worker-1",
                model="report-model",
                service=_FakeService(),  # type: ignore[arg-type]
            )
        )
