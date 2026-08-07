"""Report Builder Generation Worker의 러너 위임과 입력 검증을 검증한다."""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from workers.features import report_generation
from workers.features.report_generation import worker_003


class _FakeConnection:
    """transaction 문맥만 제공하는 Connection Test Double."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """빈 Transaction 문맥을 제공한다."""
        yield


def test_run_report_generation_batch_delegates_to_shared_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """생성 Batch가 공통 러너에 유형·오류 접두사·처리 함수를 전달한다."""
    captured: dict[str, Any] = {}

    async def fake_run_job_batch(**kwargs: Any) -> list[dict[str, object]]:
        """공통 Batch 러너 호출 인자를 기록하고 고정 결과를 반환한다."""
        captured.update(kwargs)
        return [{"job_id": "report-job-1", "status": "completed"}]

    monkeypatch.setattr(report_generation, "run_job_batch", fake_run_job_batch)

    results = asyncio.run(
        report_generation.run_report_generation_batch(
            database_url="postgresql://test",
            worker_id="worker-1",
            limit=3,
            lease_seconds=600,
            model="report-model",
        )
    )

    assert results == [{"job_id": "report-job-1", "status": "completed"}]
    assert captured["job_type"] == "report_generation"
    assert captured["error_code_prefix"] == "REPORT_GENERATION"
    assert captured["limit"] == 3
    assert callable(captured["process"])


def test_worker_003_requires_database_url() -> None:
    """WORKER-003이 DB 연결 없이 호출되면 명확한 검증 오류를 낸다."""
    with pytest.raises(ValueError, match="database_url"):
        asyncio.run(worker_003(database_url="", worker_id="worker-1"))


def _claimed_job(payload: dict[str, Any]) -> Any:
    """Lease로 점유한 Report Builder Job 대역을 만든다."""
    return SimpleNamespace(
        job_id="report-job-1",
        user_id="user-1",
        attempt_number=1,
        payload=payload,
    )


def _run_worker_job(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> dict[str, Any]:
    """운영 Worker의 Job 처리 경로를 돌리고 러너에 넘어간 인자를 돌려준다."""
    captured: dict[str, Any] = {}

    async def fake_runner(connection: Any, **kwargs: Any) -> dict[str, object]:
        """그래프 실행 인자를 기록하고 고정 결과를 반환한다."""
        captured.update(kwargs)
        return {"content_candidate_id": "candidate-1"}

    async def fake_complete(connection: Any, command: Any) -> None:
        """Job 완료 기록을 생략한다."""

    async def fake_scope(connection: Any) -> None:
        """시스템 Scope 설정을 생략한다."""

    monkeypatch.setattr(report_generation, "run_report_generation", fake_runner)
    monkeypatch.setattr(report_generation, "db_026", fake_complete)
    monkeypatch.setattr(report_generation, "set_system_job_scope", fake_scope)

    asyncio.run(
        report_generation._process_job(
            _FakeConnection(),  # type: ignore[arg-type]
            job=_claimed_job(payload),
            worker_id="worker-1",
            model="report-model",
        )
    )
    return captured


def test_worker_passes_the_change_history_toggle_from_the_job_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """운영 Worker도 Job Payload의 변경점 추적 토글을 그래프에 전달한다.

    개발 API(AgentWorkflowService)만 토글을 읽으면, Service가 켜서 보낸 요청이
    운영 큐를 타는 순간 조용히 기존 경로로 처리된다 — 실행 경로에 따라 결과가
    달라지면 안 된다.
    """
    captured = _run_worker_job(
        monkeypatch,
        {
            "topic": "반도체",
            "content_type": "interest_news_card",
            "language": "ko",
            "change_history_enabled": True,
        },
    )

    assert captured["change_history_enabled"] is True


def test_worker_defaults_the_toggle_off_for_jobs_without_the_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """플래그 도입 이전에 등록된 Job은 기존 생성 경로로 실행된다."""
    captured = _run_worker_job(
        monkeypatch,
        {"topic": "반도체", "content_type": "interest_news_card", "language": "ko"},
    )

    assert captured["change_history_enabled"] is False


def test_worker_passes_interest_bundle_snapshot_to_the_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """운영 Worker는 접수 시 고정한 관심사 묶음을 현재 Wiki 재조회 없이 전달한다."""
    bundle = {
        "root": {"keyword": "생성형 AI"},
        "neighbors": [{"keyword": "AI 에이전트"}],
        "keywords": ["생성형 AI", "AI 에이전트"],
    }
    captured = _run_worker_job(
        monkeypatch,
        {
            "topic": "생성형 AI",
            "content_type": "interest_news_card",
            "language": "ko",
            "generation_scope": "INTEREST_BUNDLE",
            "interest_bundle": bundle,
        },
    )

    assert captured["generation_scope"] == "INTEREST_BUNDLE"
    assert captured["interest_bundle"] == bundle
