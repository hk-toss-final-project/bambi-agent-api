"""LangGraph Wiki 유지 루프 V2의 감사·계획·실행과 V1 호환 라우팅을 검증한다."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent.wiki_builder.features import maintenance
from agent.wiki_builder.features.maintenance import (
    WikiMaintenanceAction,
    WikiMaintenanceAudit,
    build_wiki_maintenance_graph_v2,
    load_wiki_maintenance_audit,
    plan_wiki_maintenance,
    run_wiki_maintenance_for_version,
    run_wiki_maintenance_graph_v2,
)

_ACTIVATED_AT = datetime(2026, 8, 11, 1, 0, tzinfo=UTC)


def _audit(
    *,
    source_count: int = 2,
    active_wiki_version_id: str | None = "wiki-1",
    active_wiki_activated_at: datetime | None = _ACTIVATED_AT,
    latest_source_updated_at: datetime | None = _ACTIVATED_AT - timedelta(hours=1),
    quality_metrics: dict[str, int | float] | None = None,
    missing_ids: tuple[str, ...] = (),
) -> WikiMaintenanceAudit:
    """유지 계획 테스트용 현재 Wiki 감사 결과를 만든다."""
    return WikiMaintenanceAudit(
        user_id="user-1",
        source_count=source_count,
        latest_source_updated_at=latest_source_updated_at,
        active_wiki_version_id=active_wiki_version_id,
        active_wiki_activated_at=active_wiki_activated_at,
        quality_metrics=(
            {"document_count": 3, "error_count": 0, "warning_count": 0}
            if quality_metrics is None
            else quality_metrics
        ),
        missing_embedding_document_version_ids=missing_ids,
    )


class _Cursor:
    """감사 SQL의 fetchone·fetchall 결과를 순서대로 제공하는 Cursor 대역."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        """반환할 Row 목록을 보관한다."""
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        """첫 Row 또는 None을 반환한다."""
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        """전체 Row를 반환한다."""
        return self._rows


class _Connection:
    """유지 감사의 짧은 Transaction과 SQL 실행을 기록하는 연결 대역."""

    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        """SQL 순서와 맞춘 응답 목록을 준비한다."""
        self._responses = list(responses)
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """빈 비동기 Transaction 구간을 제공한다."""
        yield

    async def execute(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> _Cursor:
        """SQL과 파라미터를 기록하고 다음 Cursor 응답을 반환한다."""
        self.executed.append((query, params))
        return _Cursor(self._responses.pop(0))


def test_load_wiki_maintenance_audit_reads_quality_and_missing_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """감사가 활성 원본·Snapshot Metric·현재 모델의 누락 Page를 함께 읽는다."""
    connection = _Connection(
        [
            [{"source_count": 2, "latest_updated_at": _ACTIVATED_AT}],
            [
                {
                    "wiki_version_id": "wiki-1",
                    "activated_at": _ACTIVATED_AT,
                    "change_summary": {
                        "quality_metrics": {"error_count": 0, "orphan_count": 0}
                    },
                }
            ],
            [{"version_id": "version-2"}, {"version_id": "version-3"}],
        ]
    )

    async def fake_scope(*args: Any, **kwargs: Any) -> None:
        """테스트에서 RLS 설정 SQL을 생략한다."""

    monkeypatch.setattr(maintenance, "set_personal_wiki_scope", fake_scope)

    result = asyncio.run(
        load_wiki_maintenance_audit(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            embedding_model="embedding-v2",
        )
    )

    assert result.source_count == 2
    assert result.quality_metrics["error_count"] == 0
    assert result.missing_embedding_document_version_ids == (
        "version-2",
        "version-3",
    )
    assert connection.executed[2][1] == ("wiki-1", "embedding-v2")


@pytest.mark.parametrize(
    ("audit", "trigger", "expected"),
    [
        (_audit(), "maintenance", WikiMaintenanceAction.NOOP),
        (
            _audit(missing_ids=("version-1",)),
            "maintenance",
            WikiMaintenanceAction.REPAIR_DERIVATIVES,
        ),
        (_audit(), "source_deleted", WikiMaintenanceAction.FULL_REBUILD),
        (_audit(source_count=0), "maintenance", WikiMaintenanceAction.FULL_REBUILD),
        (
            _audit(quality_metrics={"error_count": 1}),
            "maintenance",
            WikiMaintenanceAction.FULL_REBUILD,
        ),
        (
            _audit(latest_source_updated_at=_ACTIVATED_AT + timedelta(minutes=1)),
            "maintenance",
            WikiMaintenanceAction.FULL_REBUILD,
        ),
    ],
)
def test_plan_wiki_maintenance_selects_minimum_safe_action(
    audit: WikiMaintenanceAudit,
    trigger: str,
    expected: WikiMaintenanceAction,
) -> None:
    """감사 결과마다 안전한 최소 범위의 유지 action을 선택한다."""
    assert plan_wiki_maintenance(audit, trigger=trigger).action is expected


def test_maintenance_v2_graph_exposes_audit_plan_and_execution_nodes() -> None:
    """V2 그래프가 유지 판단과 실제 복구 단계를 독립 노드로 드러낸다."""
    assert set(build_wiki_maintenance_graph_v2().get_graph().nodes) == {
        "__start__",
        "audit",
        "plan",
        "repair_derivatives",
        "full_rebuild",
        "finalize",
        "__end__",
    }


def test_v2_noop_skips_embedding_and_full_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """건강한 정기 감사는 LLM 재분류와 Embedding 호출 없이 완료된다."""
    async def fake_audit(*args: Any, **kwargs: Any) -> WikiMaintenanceAudit:
        """건강한 Snapshot 감사 결과를 반환한다."""
        return _audit()

    async def unexpected_rebuild(*args: Any, **kwargs: Any) -> dict[str, object]:
        """noop에서 전체 재구성이 호출되면 실패한다."""
        raise AssertionError("건강한 Wiki를 전체 재구성하면 안 됩니다.")

    async def unexpected_embedding(*args: Any, **kwargs: Any) -> int:
        """noop에서 Embedding이 호출되면 실패한다."""
        raise AssertionError("건강한 Wiki를 재임베딩하면 안 됩니다.")

    monkeypatch.setattr(maintenance, "load_wiki_maintenance_audit", fake_audit)
    monkeypatch.setattr(maintenance, "wba_011", unexpected_embedding)

    result = asyncio.run(
        run_wiki_maintenance_graph_v2(
            object(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            trigger="maintenance",
            rebuild_runner=unexpected_rebuild,
        )
    )

    assert result["maintenance_action"] == "noop"
    assert result["maintenance_pipeline_version"] == "langgraph_v2"
    assert result["maintenance_audit"]["source_count"] == 2


def test_v2_repairs_only_missing_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """구조가 건강하면 누락 문서만 WBA-011에 전달하고 Full Rebuild를 건너뛴다."""
    captured: dict[str, Any] = {}

    async def fake_audit(*args: Any, **kwargs: Any) -> WikiMaintenanceAudit:
        """Embedding 두 문서만 빠진 감사 결과를 반환한다."""
        return _audit(missing_ids=("version-2", "version-3"))

    async def fake_embedding(*args: Any, **kwargs: Any) -> int:
        """재임베딩 인자를 기록하고 저장 건수를 반환한다."""
        captured.update(kwargs)
        return 4

    async def unexpected_rebuild(*args: Any, **kwargs: Any) -> dict[str, object]:
        """파생 복구에서 전체 재구성이 호출되면 실패한다."""
        raise AssertionError("Embedding 누락만으로 전체 재구성하면 안 됩니다.")

    monkeypatch.setattr(maintenance, "load_wiki_maintenance_audit", fake_audit)
    monkeypatch.setattr(maintenance, "wba_011", fake_embedding)

    result = asyncio.run(
        run_wiki_maintenance_graph_v2(
            object(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            trigger="maintenance",
            rebuild_runner=unexpected_rebuild,
            embedding_model="embedding-v2",
        )
    )

    assert captured["document_version_ids"] == ("version-2", "version-3")
    assert captured["model"] == "embedding-v2"
    assert result["maintenance_action"] == "repair_derivatives"
    assert result["embedding_count"] == 4


def test_v2_source_deletion_reuses_legacy_atomic_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """원본 제거는 검증된 V1 실행기를 한 번 호출해 원자 교체 의미를 보존한다."""
    calls: list[dict[str, Any]] = []

    async def fake_audit(*args: Any, **kwargs: Any) -> WikiMaintenanceAudit:
        """구조 자체는 건강한 감사 결과를 반환한다."""
        return _audit()

    async def fake_rebuild(connection: Any, **kwargs: Any) -> dict[str, object]:
        """원자 재구성 호출 인자를 기록하고 고정 결과를 반환한다."""
        calls.append(kwargs)
        return {"full_rebuild": True, "wiki_version_id": "wiki-2"}

    monkeypatch.setattr(maintenance, "load_wiki_maintenance_audit", fake_audit)

    result = asyncio.run(
        run_wiki_maintenance_graph_v2(
            object(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            trigger="source_deleted",
            rebuild_runner=fake_rebuild,
        )
    )

    assert len(calls) == 1
    assert result["wiki_version_id"] == "wiki-2"
    assert result["maintenance_action"] == "full_rebuild"


def test_version_router_keeps_legacy_runner_result_contract() -> None:
    """버전 필드가 없는 과거 Job은 V1 실행기와 결과 Payload를 그대로 유지한다."""
    calls: list[str] = []

    async def fake_rebuild(connection: Any, **kwargs: Any) -> dict[str, object]:
        """V1 원자 재구성 호출을 기록한다."""
        calls.append(kwargs["job_id"])
        return {"full_rebuild": True}

    result = asyncio.run(
        run_wiki_maintenance_for_version(
            object(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            trigger="legacy_full_rebuild",
            rebuild_runner=fake_rebuild,
        )
    )

    assert calls == ["job-1"]
    assert result == {"full_rebuild": True}


def test_version_router_rejects_unknown_maintenance_version() -> None:
    """잘못된 유지 버전을 조용히 V1이나 V2로 폴백하지 않는다."""
    async def fake_rebuild(*args: Any, **kwargs: Any) -> dict[str, object]:
        """잘못된 버전에서는 호출되지 않을 재구성 대역이다."""
        return {}

    with pytest.raises(ValueError, match="지원하지 않는"):
        asyncio.run(
            run_wiki_maintenance_for_version(
                object(),  # type: ignore[arg-type]
                pipeline_version="v3",
                user_id="user-1",
                job_id="job-1",
                trigger="maintenance",
                rebuild_runner=fake_rebuild,
            )
        )
