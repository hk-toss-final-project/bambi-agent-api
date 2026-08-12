"""Wiki 유지 V3의 구조·의미 감사, 수리·조사와 버전 라우팅을 검증한다."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent.wiki_builder.features import maintenance, maintenance_v3
from agent.wiki_builder.features.maintenance import (
    WikiMaintenanceAction,
    WikiMaintenanceAudit,
    run_wiki_maintenance_for_version,
)
from agent.wiki_builder.features.maintenance_v3 import (
    WikiSemanticSnapshot,
    build_wiki_maintenance_graph_v3,
    plan_wiki_maintenance_v3,
    run_wiki_maintenance_graph_v3,
)
from agent.wiki_builder.features.quality import validate_wiki_quality
from agent.wiki_builder.features.semantic_audit import (
    WikiMissingTopicProposal,
    WikiSemanticEvidence,
    WikiSemanticIssue,
    WikiSemanticIssueCode,
    WikiSemanticLintReport,
)
from agent.wiki_builder.features.semantic_repairs import WikiSemanticRepairResult
from agent.wiki_builder.features.knowledge_gap_research import (
    WikiKnowledgeGapResearchResult,
)
from infrastructure.persistence.api import UserSourceDocumentForAgent
from shared.wiki_models import ExistingWikiEntry

_ACTIVATED_AT = datetime(2026, 8, 12, 1, 0, tzinfo=UTC)


class _Connection:
    """유지 요약과 외부 등록의 Transaction 횟수를 기록하는 연결 대역."""

    def __init__(self) -> None:
        """Transaction 횟수를 0으로 초기화한다."""
        self.transactions = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """진입 횟수만 기록하는 빈 비동기 Transaction을 제공한다."""
        self.transactions += 1
        yield


def _audit(
    *,
    quality_metrics: dict[str, int | float] | None = None,
    missing_ids: tuple[str, ...] = (),
) -> WikiMaintenanceAudit:
    """V3 계획·실행 테스트용 건강한 운영 감사 결과를 만든다."""
    return WikiMaintenanceAudit(
        user_id="user-1",
        source_count=1,
        latest_source_updated_at=_ACTIVATED_AT - timedelta(hours=1),
        active_wiki_version_id="wiki-v1",
        active_wiki_activated_at=_ACTIVATED_AT,
        quality_metrics=(
            {"document_count": 1, "error_count": 0}
            if quality_metrics is None
            else quality_metrics
        ),
        missing_embedding_document_version_ids=missing_ids,
    )


def _source() -> UserSourceDocumentForAgent:
    """의미 감사 Context에 넣을 활성 원본 Version을 만든다."""
    return UserSourceDocumentForAgent(
        source_document_id="source-1",
        source_document_version_id="source-v1",
        source_event_id="event-1",
        user_id="user-1",
        namespace_key="user/user-1",
        source_type="web_clipping",
        canonical_url="https://example.com/source",
        version=1,
        title="기후 기록",
        author=None,
        published_at=None,
        clipped_on=None,
        description=None,
        tags=["climate"],
        raw_content="열대야가 10일 지속됐다.",
        content_hash="a" * 64,
    )


def _entry(*, title: str = "폭염", key: str = "heatwave") -> ExistingWikiEntry:
    """구조·의미 감사에 넣을 현재 Concept Page를 만든다."""
    return ExistingWikiEntry(
        document_kind="concept",
        document_key=key,
        title=title,
        domain="other",
        summary="고온 현상",
        metadata={"sources": ["[[sources/climate|기후 기록]]"]},
    )


def _snapshot(*entries: ExistingWikiEntry) -> WikiSemanticSnapshot:
    """고정 원본과 전달받은 Page를 포함한 현재 Snapshot을 만든다."""
    return WikiSemanticSnapshot(
        sources=(_source(),),
        entries=entries or (_entry(),),
        relations=(),
    )


def _empty_report() -> WikiSemanticLintReport:
    """의미 문제를 찾지 못한 검증 보고서를 만든다."""
    return WikiSemanticLintReport(
        issues=(),
        warnings=(),
        metrics={"issue_count": 0},
        model="model-test",
    )


def test_maintenance_v3_graph_exposes_semantic_and_repair_nodes() -> None:
    """운영·구조·의미 감사와 수리·조사·요약 단계가 독립 노드로 드러난다."""
    assert set(build_wiki_maintenance_graph_v3().get_graph().nodes) == {
        "__start__",
        "operational_audit",
        "plan_operational",
        "full_rebuild",
        "load_snapshot",
        "structural_lint",
        "structural_failure",
        "generate_candidates",
        "semantic_lint",
        "plan_repairs",
        "apply_internal_repairs",
        "research_knowledge_gaps",
        "repair_derivatives",
        "refresh_interest_profile",
        "persist_summary",
        "finalize",
        "__end__",
    }


def test_v3_plan_does_not_treat_semantic_warnings_as_structural_rebuild() -> None:
    """모순·고아 경고는 의미 감사에서 처리하고 저장 지표만으로 재구성하지 않는다."""
    plan = plan_wiki_maintenance_v3(
        _audit(
            quality_metrics={
                "error_count": 0,
                "contradiction_count": 3,
                "orphan_count": 5,
            }
        ),
        trigger="maintenance",
    )

    assert plan.action is WikiMaintenanceAction.NOOP


def test_v3_healthy_snapshot_runs_semantic_audit_without_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """운영·구조가 건강해도 의미 감사를 한 번 실행하고 지표를 Snapshot에 남긴다."""
    connection = _Connection()
    summaries: list[dict[str, Any]] = []
    completion_calls = 0

    async def fake_audit(*args: Any, **kwargs: Any) -> WikiMaintenanceAudit:
        """건강한 운영 감사 결과를 반환한다."""
        return _audit()

    async def fake_snapshot(*args: Any, **kwargs: Any) -> WikiSemanticSnapshot:
        """현재 원본과 Page Snapshot을 반환한다."""
        return _snapshot()

    async def fake_scope(*args: Any, **kwargs: Any) -> None:
        """테스트에서 실제 RLS SQL을 생략한다."""

    async def fake_summary(*args: Any, **kwargs: Any) -> None:
        """저장할 V3 감사 요약을 기록한다."""
        summaries.append(kwargs)

    async def unexpected_rebuild(*args: Any, **kwargs: Any) -> dict[str, object]:
        """건강한 Snapshot에서 재구성이 호출되면 실패한다."""
        raise AssertionError("건강한 Wiki를 전체 재구성하면 안 됩니다.")

    def completion(system: str, user: str, *, model: str) -> str:
        """실제 Prompt 경계를 기록하고 빈 의미 문제 JSON을 반환한다."""
        nonlocal completion_calls
        completion_calls += 1
        return json.dumps({"issues": []})

    def unexpected_collector(*args: Any, **kwargs: Any) -> list[Any]:
        """지식 공백 없이 외부 수집이 호출되면 실패한다."""
        raise AssertionError("지식 공백 없이 외부 조사하면 안 됩니다.")

    monkeypatch.setattr(maintenance_v3, "load_wiki_maintenance_audit", fake_audit)
    monkeypatch.setattr(maintenance_v3, "load_wiki_semantic_snapshot", fake_snapshot)
    monkeypatch.setattr(maintenance_v3, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(maintenance_v3, "update_wiki_maintenance_summary", fake_summary)

    result = asyncio.run(
        run_wiki_maintenance_graph_v3(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            trigger="maintenance",
            model="model-test",
            full_rebuild_runner=unexpected_rebuild,
            semantic_completion=completion,
            knowledge_collector=unexpected_collector,
        )
    )

    assert completion_calls == 1
    assert connection.transactions == 1
    assert summaries[0]["wiki_version_id"] == "wiki-v1"
    assert summaries[0]["semantic_metrics"]["issue_count"] == 0
    assert result["maintenance_pipeline_version"] == "langgraph_v3"
    assert result["maintenance_action"] == "semantic_audit"
    assert result["semantic_lint"]["metrics"]["issue_count"] == 0


def test_v3_applies_internal_repairs_and_enqueues_external_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """한 의미 보고서의 누락 주제는 내부 수리하고 지식 공백은 쓰기 큐로 넘긴다."""
    connection = _Connection()
    captured_plan: list[Any] = []
    summaries: list[dict[str, Any]] = []
    quality = validate_wiki_quality([_entry()], [])
    topic_issue = WikiSemanticIssue(
        issue_id="issue-topic",
        code=WikiSemanticIssueCode.MISSING_TOPIC,
        severity="warning",
        title="누락 주제",
        rationale="원문에서 반복됩니다.",
        confidence=0.9,
        page_references=("P1",),
        source_references=("S1",),
        evidence=(WikiSemanticEvidence("S1", "열대야가 10일 지속됐다."),),
        topic=WikiMissingTopicProposal(
            document_kind="concept",
            title="열대야",
            summary="밤에도 이어지는 고온 현상",
            aliases=(),
        ),
    )
    gap_issue = WikiSemanticIssue(
        issue_id="issue-gap",
        code=WikiSemanticIssueCode.KNOWLEDGE_GAP,
        severity="warning",
        title="외부 공백",
        rationale="최신 장기 추세가 없습니다.",
        confidence=0.9,
        page_references=("P1",),
        source_references=(),
        evidence=(),
        research_query="서울 열대야 장기 추세",
    )
    report = WikiSemanticLintReport(
        issues=(topic_issue, gap_issue),
        warnings=(),
        metrics={"issue_count": 2, "missing_topic_count": 1},
        model="model-test",
    )

    async def fake_audit(*args: Any, **kwargs: Any) -> WikiMaintenanceAudit:
        """건강한 운영 감사 결과를 반환한다."""
        return _audit()

    async def fake_snapshot(*args: Any, **kwargs: Any) -> WikiSemanticSnapshot:
        """현재 원본과 Page Snapshot을 반환한다."""
        return _snapshot()

    def fake_semantic(*args: Any, **kwargs: Any) -> WikiSemanticLintReport:
        """누락 주제와 외부 지식 공백 보고서를 반환한다."""
        return report

    async def fake_apply(*args: Any, **kwargs: Any) -> WikiSemanticRepairResult:
        """계획을 기록하고 내부 수리 결과를 반환한다."""
        captured_plan.append(kwargs["repair_plan"])
        return WikiSemanticRepairResult(
            wiki_version_id="wiki-v2",
            repaired_issue_ids=("issue-topic",),
            changed_document_version_ids=("document-v2",),
            affected_document_count=1,
            stored_relation_count=0,
            embedding_count=1,
            quality=quality,
        )

    async def fake_research(*args: Any, **kwargs: Any) -> WikiKnowledgeGapResearchResult:
        """지식 공백 한 건을 기존 URL 수집 큐에 등록한 결과를 반환한다."""
        assert [issue.issue_id for issue in kwargs["issues"]] == ["issue-gap"]
        return WikiKnowledgeGapResearchResult(
            query_count=1,
            collected_document_count=2,
            queued_source_count=1,
            source_event_ids=("wiki-v3:issue-gap:hash",),
            warnings=(),
        )

    async def fake_scope(*args: Any, **kwargs: Any) -> None:
        """테스트에서 실제 RLS SQL을 생략한다."""

    async def fake_summary(*args: Any, **kwargs: Any) -> None:
        """최종 의미 감사 요약을 기록한다."""
        summaries.append(kwargs)

    async def fake_interest_refresh(*args: Any, **kwargs: Any) -> dict[str, object]:
        """Wiki 변경 뒤 관심사 Profile 갱신 결과를 반환한다."""
        return {
            "refreshed": True,
            "version": 2,
            "subscribed_target_count": 1,
            "warning": None,
        }

    async def unexpected_rebuild(*args: Any, **kwargs: Any) -> dict[str, object]:
        """건강한 Snapshot에서 재구성이 호출되면 실패한다."""
        raise AssertionError("건강한 Wiki를 재구성하면 안 됩니다.")

    monkeypatch.setattr(maintenance_v3, "load_wiki_maintenance_audit", fake_audit)
    monkeypatch.setattr(maintenance_v3, "load_wiki_semantic_snapshot", fake_snapshot)
    monkeypatch.setattr(maintenance_v3, "audit_wiki_semantics", fake_semantic)
    monkeypatch.setattr(maintenance_v3, "apply_wiki_semantic_repairs", fake_apply)
    monkeypatch.setattr(maintenance_v3, "research_wiki_knowledge_gaps", fake_research)
    monkeypatch.setattr(maintenance_v3, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(maintenance_v3, "update_wiki_maintenance_summary", fake_summary)
    monkeypatch.setattr(
        maintenance_v3,
        "refresh_wiki_interest_profile",
        fake_interest_refresh,
    )

    result = asyncio.run(
        run_wiki_maintenance_graph_v3(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            trigger="maintenance",
            full_rebuild_runner=unexpected_rebuild,
        )
    )

    assert captured_plan[0].metrics["planned_internal_issue_count"] == 1
    assert summaries[0]["wiki_version_id"] == "wiki-v2"
    assert summaries[0]["maintenance_action"] == "semantic_repair"
    assert result["maintenance_action"] == "semantic_repair"
    assert result["semantic_repair"]["repaired_issue_count"] == 1
    assert result["knowledge_gap_research"]["queued_source_count"] == 1
    assert result["interest_profile_refresh"]["refreshed"] is True


def test_v3_fresh_structural_error_runs_full_rebuild_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """저장 지표가 건강해도 현재 구조 오류를 찾으면 V3 재구성 후 다시 감사한다."""
    connection = _Connection()
    snapshots = [
        _snapshot(_entry(title="같은 제목", key="one"), _entry(title="같은 제목", key="two")),
        _snapshot(_entry()),
    ]
    rebuild_calls = 0

    async def fake_audit(*args: Any, **kwargs: Any) -> WikiMaintenanceAudit:
        """저장된 지표상 건강한 운영 감사 결과를 반환한다."""
        return _audit()

    async def fake_snapshot(*args: Any, **kwargs: Any) -> WikiSemanticSnapshot:
        """재구성 전 오류 Snapshot과 재구성 후 건강한 Snapshot을 순서대로 반환한다."""
        return snapshots.pop(0)

    async def fake_rebuild(*args: Any, **kwargs: Any) -> dict[str, object]:
        """V3 전체 재구성 호출 횟수와 새 Snapshot ID를 반환한다."""
        nonlocal rebuild_calls
        rebuild_calls += 1
        return {"full_rebuild": True, "wiki_version_id": "wiki-v2"}

    def fake_semantic(*args: Any, **kwargs: Any) -> WikiSemanticLintReport:
        """재구성 후 의미 문제가 없다고 반환한다."""
        return _empty_report()

    async def fake_scope(*args: Any, **kwargs: Any) -> None:
        """테스트에서 실제 RLS SQL을 생략한다."""

    async def fake_summary(*args: Any, **kwargs: Any) -> None:
        """테스트에서 실제 요약 SQL을 생략한다."""

    monkeypatch.setattr(maintenance_v3, "load_wiki_maintenance_audit", fake_audit)
    monkeypatch.setattr(maintenance_v3, "load_wiki_semantic_snapshot", fake_snapshot)
    monkeypatch.setattr(maintenance_v3, "audit_wiki_semantics", fake_semantic)
    monkeypatch.setattr(maintenance_v3, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(maintenance_v3, "update_wiki_maintenance_summary", fake_summary)

    result = asyncio.run(
        run_wiki_maintenance_graph_v3(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            trigger="maintenance",
            full_rebuild_runner=fake_rebuild,
        )
    )

    assert rebuild_calls == 1
    assert snapshots == []
    assert result["maintenance_action"] == "full_rebuild"
    assert result["wiki_version_id"] == "wiki-v2"


def test_version_router_dispatches_exact_langgraph_v3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Job에 고정된 langgraph_v3만 새 유지 그래프로 보내고 결과를 그대로 반환한다."""
    calls: list[str] = []

    async def fake_v3(*args: Any, **kwargs: Any) -> dict[str, object]:
        """V3 Router 호출 Job ID를 기록한다."""
        calls.append(kwargs["job_id"])
        return {"maintenance_pipeline_version": "langgraph_v3"}

    async def unexpected_legacy(*args: Any, **kwargs: Any) -> dict[str, object]:
        """V3 Job에서 Legacy 재구성기가 호출되면 실패한다."""
        raise AssertionError("V3 Job을 Legacy 실행기로 보내면 안 됩니다.")

    monkeypatch.setattr(maintenance_v3, "run_wiki_maintenance_graph_v3", fake_v3)

    result = asyncio.run(
        run_wiki_maintenance_for_version(
            object(),  # type: ignore[arg-type]
            pipeline_version="langgraph_v3",
            user_id="user-1",
            job_id="job-1",
            trigger="maintenance",
            rebuild_runner=unexpected_legacy,
        )
    )

    assert calls == ["job-1"]
    assert result["maintenance_pipeline_version"] == "langgraph_v3"
