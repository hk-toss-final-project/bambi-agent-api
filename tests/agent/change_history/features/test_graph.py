"""변경점 추적 서브그래프의 Supervisor 경로와 저장 계약을 검증한다.

LLM(diff·compose·impact)과 DB(prepare·validate·store)를 모두 대체하고,
Supervisor가 상태에 따라 실제로 다른 경로를 택하는지 확인한다.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import pytest

from agent.change_history.features import graph as graph_module
from agent.change_history.features.compose import ComposeOutcome, TimelineDraft
from agent.change_history.features.diff import DiffFact, DiffOutcome
from agent.change_history.features.impact import ImpactOutcome
from agent.change_history.features.validation import (
    DIFF_WORKER,
    IMPACT_WORKER,
    ValidatedFact,
    ValidationOutcome,
    ValidationProblem,
)
from shared.change_history_models import PersistedChangeHistoryRun
from shared.report_models import GeneratedReportContent, ReportContextDocument

REFERENCE_DATE = date(2026, 8, 5)


class _FakeConnection:
    """transaction 문맥만 제공하는 Connection Test Double."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """빈 Transaction 문맥을 제공한다."""
        yield


def _context(reference: str = "G1") -> ReportContextDocument:
    """테스트용 근거 문서를 만든다."""
    return ReportContextDocument(
        reference=reference,
        document_version_id=f"ver-{reference}",
        chunk_id=f"chunk-{reference}",
        namespace_key="global",
        title="기사",
        content="본문",
        url=None,
        score=0.5,
    )


def _fact(verdict: str = "new") -> DiffFact:
    """테스트용 팩트를 만든다."""
    return DiffFact(
        verdict=verdict,
        subject="B사 HBM4",
        attribute="양산 일정",
        fact_value="2026-3Q",
        today_statement="양산이 연기됐다.",
        updates_fact_id="fact-1" if verdict == "updated" else None,
        source_reference="G1",
    )


def _patch_graph(
    monkeypatch: pytest.MonkeyPatch,
    *,
    order: list[str],
    stored: list[dict[str, Any]],
    base_available: bool = True,
    diff_outcomes: list[DiffOutcome] | None = None,
    validations: list[ValidationOutcome] | None = None,
) -> None:
    """서브그래프의 LLM·DB 경계를 모두 대체한다."""
    diff_queue = list(
        diff_outcomes or [DiffOutcome(facts=(_fact(),))]
    )
    validation_queue = list(
        validations
        or [ValidationOutcome(facts=(ValidatedFact(fact=_fact()),))]
    )

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """RLS Scope 설정을 생략한다."""

    async def fake_snapshot(connection: Any, **kwargs: Any) -> None:
        """직전 발행 Snapshot이 없는 상태를 재현한다."""
        return None

    async def fake_run(connection: Any, **kwargs: Any) -> None:
        """직전 델타 실행이 없는 상태를 재현한다."""
        return None

    async def fake_list(connection: Any, **kwargs: Any) -> list[Any]:
        """Base 팩트 존재 여부만 흉내낸다."""
        return [object()] if base_available else []

    async def fake_diff(connection: Any, **kwargs: Any) -> DiffOutcome:
        """Diff worker 호출을 기록하고 정해진 결과를 돌려준다."""
        order.append("diff")
        return diff_queue.pop(0) if diff_queue else DiffOutcome()

    async def fake_compose(**kwargs: Any) -> ComposeOutcome:
        """Compose worker 호출을 기록한다."""
        order.append("compose")
        return ComposeOutcome(
            title="제목",
            summary="요약",
            overview="브리핑 [G1]",
            timeline=(
                TimelineDraft(
                    fact_index=0,
                    raw_date="2026-08-04",
                    precision="day",
                    description="발표 [G1]",
                ),
            ),
        )

    async def fake_impact(**kwargs: Any) -> ImpactOutcome:
        """Impact worker 호출을 기록한다."""
        order.append("impact")
        return ImpactOutcome(implications="파급 [G1]", actions=("확인",))

    async def fake_validate(connection: Any, **kwargs: Any) -> ValidationOutcome:
        """검증 호출을 기록하고 정해진 결과를 돌려준다."""
        order.append("validate")
        return validation_queue.pop(0) if validation_queue else ValidationOutcome()

    async def fake_persist(connection: Any, **kwargs: Any) -> PersistedChangeHistoryRun:
        """저장 호출 인자를 기록한다."""
        order.append("store")
        stored.append(dict(kwargs))
        return PersistedChangeHistoryRun(run_id="run-1", fact_ids=("new-fact-1",))

    monkeypatch.setattr(graph_module, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(graph_module, "load_latest_report_snapshot", fake_snapshot)
    monkeypatch.setattr(graph_module, "load_latest_change_history_run", fake_run)
    monkeypatch.setattr(graph_module, "list_change_history_facts", fake_list)
    monkeypatch.setattr(graph_module, "chg_002", fake_diff)
    monkeypatch.setattr(graph_module, "chg_003", fake_compose)
    monkeypatch.setattr(graph_module, "chg_004", fake_impact)
    monkeypatch.setattr(graph_module, "chg_005", fake_validate)
    monkeypatch.setattr(graph_module, "persist_change_history_run", fake_persist)


def _run() -> dict[str, Any]:
    """서브그래프를 고정 입력으로 실행한다."""
    return asyncio.run(
        graph_module.chg_001(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            job_id="job-1",
            topic="반도체",
            contexts=[_context()],
            model="test-model",
            reference_date=REFERENCE_DATE,
        )
    )


def test_full_path_runs_workers_then_validates_then_stores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """정상 경로는 diff → compose → impact → validate → store 순서로 흐른다."""
    order: list[str] = []
    stored: list[dict[str, Any]] = []
    _patch_graph(monkeypatch, order=order, stored=stored)

    result = _run()

    assert order == ["diff", "compose", "impact", "validate", "store"]
    assert isinstance(result["generated"], GeneratedReportContent)
    assert result["run_id"] == "run-1"


def test_first_run_skips_base_lookup_but_still_stores_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """첫 실행도 팩트를 저장해 내일의 Base를 만든다."""
    order: list[str] = []
    stored: list[dict[str, Any]] = []
    _patch_graph(monkeypatch, order=order, stored=stored, base_available=False)

    result = _run()

    assert result["is_first_run"] is True
    assert stored[0]["is_first_run"] is True
    assert len(stored[0]["facts"]) == 1  # 첫 실행에도 팩트가 저장된다
    assert result["stored_fact_count"] == 1
    assert "최초 실행" in result["generated"].body


def test_all_duplicates_take_the_short_no_change_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전부 중복이면 Compose·Impact를 건너뛰고 짧은 보고서로 간다."""
    order: list[str] = []
    stored: list[dict[str, Any]] = []
    _patch_graph(
        monkeypatch,
        order=order,
        stored=stored,
        diff_outcomes=[DiffOutcome(facts=(_fact("duplicate"), _fact("duplicate")))],
    )

    result = _run()

    assert order == ["diff", "store"]  # LLM 2콜을 아낀다
    assert result["no_change"] is True
    assert stored[0]["outcome"] == "no_change"
    assert stored[0]["duplicate_fact_count"] == 2
    assert stored[0]["facts"] == []


def test_validation_failure_retries_only_the_failing_worker_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """검증이 실패하면 문제가 난 워커만 1회 재작업하고, 그 뒤엔 드롭 후 통과한다."""
    order: list[str] = []
    stored: list[dict[str, Any]] = []
    problem = ValidationProblem(
        worker=DIFF_WORKER,
        reason="updates_fact_id_not_found",
        subject="B사 HBM4 / 양산 일정",
    )
    _patch_graph(
        monkeypatch,
        order=order,
        stored=stored,
        diff_outcomes=[
            DiffOutcome(facts=(_fact("updated"),)),
            DiffOutcome(facts=(_fact("updated"),)),
        ],
        validations=[
            ValidationOutcome(problems=(problem,)),
            ValidationOutcome(problems=(problem,)),
        ],
    )

    result = _run()

    # diff가 정확히 한 번만 재작업되고, 두 번째 실패에서는 무한 루프 대신 드롭한다.
    assert order.count("diff") == 2
    assert order[-1] == "store"
    assert result["dropped_flags"][0]["reason"] == "updates_fact_id_not_found"
    assert stored[0]["dropped_flags"][0]["worker"] == DIFF_WORKER


def test_store_failure_does_not_block_publishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """델타 저장이 실패해도 이미 만든 보고서는 그대로 나간다."""
    order: list[str] = []
    stored: list[dict[str, Any]] = []
    _patch_graph(monkeypatch, order=order, stored=stored)

    async def broken_persist(connection: Any, **kwargs: Any) -> Any:
        """저장 장애를 재현한다."""
        raise RuntimeError("db down")

    monkeypatch.setattr(graph_module, "persist_change_history_run", broken_persist)

    result = _run()

    assert result["run_id"] == ""
    assert isinstance(result["generated"], GeneratedReportContent)


def test_missing_citation_retries_only_the_impact_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """시사점에 인용 마커가 없으면 Impact worker만 1회 다시 시킨다.

    Compose·Diff까지 다시 돌리면 멀쩡한 출력을 버리고 비용만 두 배가 된다.
    """
    order: list[str] = []
    stored: list[dict[str, Any]] = []
    problem = ValidationProblem(
        worker=IMPACT_WORKER, reason="implications_missing_citation"
    )
    _patch_graph(
        monkeypatch,
        order=order,
        stored=stored,
        validations=[
            ValidationOutcome(
                facts=(ValidatedFact(fact=_fact()),), problems=(problem,)
            ),
            ValidationOutcome(facts=(ValidatedFact(fact=_fact()),)),
        ],
    )

    _run()

    assert order == [
        "diff",
        "compose",
        "impact",
        "validate",
        "impact",  # 문제가 난 워커만 재작업
        "validate",
        "store",
    ]
    assert order.count("compose") == 1
    assert order.count("diff") == 1


def test_no_change_report_skips_the_quality_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'변화 없음' 보고서에는 기존 품질 검사를 적용하지 않는다.

    쓸 팩트가 없어 인용도 없는 것이 정상인데, quality는 인용 0개를 무조건
    no_citations(재생성 대상)로 본다. 고칠 수 없는 실패를 매번 기록하면
    로그와 지표가 오염된다.
    """
    order: list[str] = []
    stored: list[dict[str, Any]] = []
    _patch_graph(
        monkeypatch,
        order=order,
        stored=stored,
        diff_outcomes=[DiffOutcome(facts=(_fact("duplicate"),))],
    )

    result = _run()

    assert result["no_change"] is True
    assert result["quality_outcome"] == graph_module.QUALITY_SKIPPED_NO_CHANGE


def test_normal_report_still_runs_the_quality_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """팩트가 있는 보고서는 기존 품질 검사를 그대로 거친다."""
    order: list[str] = []
    stored: list[dict[str, Any]] = []
    _patch_graph(monkeypatch, order=order, stored=stored)

    result = _run()

    assert result["quality_outcome"] != graph_module.QUALITY_SKIPPED_NO_CHANGE
