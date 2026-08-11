"""Personal Wiki Builder Worker의 공통 러너 위임을 검증한다."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from infrastructure.persistence.api import ClaimedAgentJob
from workers.features import personal_wiki_builder


class _FakeConnection:
    """Wiki Worker 완료 처리에 필요한 Transaction 문맥만 제공한다."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """빈 비동기 Transaction 문맥을 제공한다."""
        yield


def _full_rebuild_job(pipeline_version: str) -> ClaimedAgentJob:
    """지정한 유지 버전을 Payload에 고정한 전체 재구성 Job을 만든다."""
    return ClaimedAgentJob(
        job_id="job-1",
        user_id="user-1",
        feature_id="WBA-002",
        job_type="personal_wiki_build",
        attempt_number=1,
        max_attempts=3,
        payload={
            "mode": "full_rebuild",
            "trigger": "scheduled_maintenance",
            "maintenance_pipeline_version": pipeline_version,
        },
    )


def test_run_personal_wiki_batch_delegates_to_shared_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wiki Batch가 공통 러너에 유형·오류 접두사·처리 함수를 전달한다."""
    captured: dict[str, Any] = {}

    async def fake_run_job_batch(**kwargs: Any) -> list[dict[str, object]]:
        """공통 Batch 러너 호출 인자를 기록하고 고정 결과를 반환한다."""
        captured.update(kwargs)
        return [{"job_id": "job-1", "status": "completed"}]

    monkeypatch.setattr(
        personal_wiki_builder, "run_job_batch", fake_run_job_batch
    )

    results = asyncio.run(
        personal_wiki_builder.run_personal_wiki_batch(
            database_url="postgresql://test",
            worker_id="worker-1",
            limit=5,
            lease_seconds=600,
            model="wiki-model",
        )
    )

    assert results == [{"job_id": "job-1", "status": "completed"}]
    assert captured["job_type"] == "personal_wiki_build"
    assert captured["error_code_prefix"] == "WIKI_BUILD"
    assert captured["worker_id"] == "worker-1"
    assert callable(captured["process"])
    assert captured["serialization_key"](
        type("Job", (), {"user_id": "user-1"})()
    ) == "personal_wiki_build:user-1"


def test_process_job_uses_pinned_maintenance_pipeline_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker가 현재 설정 대신 Job에 고정된 유지 V2 버전과 트리거를 실행한다."""
    captured: dict[str, Any] = {}

    async def fake_maintenance(connection: Any, **kwargs: Any) -> dict[str, object]:
        """유지 라우터 호출 인자를 기록하고 완료 결과를 반환한다."""
        captured.update(kwargs)
        return {"maintenance_action": "noop"}

    async def fake_link(result: dict[str, object]) -> dict[str, object]:
        """테스트에서는 결과 연결을 그대로 통과시킨다."""
        return result

    async def fake_scope(connection: Any) -> None:
        """테스트에서는 시스템 RLS Scope 설정을 생략한다."""

    async def fake_complete(connection: Any, command: Any) -> None:
        """테스트에서는 Job 완료 SQL을 생략한다."""

    monkeypatch.setattr(
        personal_wiki_builder,
        "run_wiki_maintenance_for_version",
        fake_maintenance,
    )
    monkeypatch.setattr(personal_wiki_builder, "job_007", fake_link)
    monkeypatch.setattr(personal_wiki_builder, "set_system_job_scope", fake_scope)
    monkeypatch.setattr(personal_wiki_builder, "db_026", fake_complete)

    result = asyncio.run(
        personal_wiki_builder._process_job(
            _FakeConnection(),  # type: ignore[arg-type]
            job=_full_rebuild_job("langgraph_v2"),
            worker_id="worker-1",
            model="wiki-model",
            embedding_batch_threshold=20,
        )
    )

    assert result["maintenance_action"] == "noop"
    assert captured["pipeline_version"] == "langgraph_v2"
    assert captured["trigger"] == "scheduled_maintenance"
    assert captured["model"] == "wiki-model"
