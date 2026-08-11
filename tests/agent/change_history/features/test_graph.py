"""변경점 추적 서브그래프의 Supervisor 경로와 저장 계약을 검증한다.

LLM(diff·compose·impact)과 DB(prepare·validate·store)를 모두 대체하고,
Supervisor가 상태에 따라 실제로 다른 경로를 택하는지 확인한다.

이 보고서는 "달라진 것만" 보여주는 문서가 아니라 평소 요약 보고서 + 달라진 점
하이라이트라는 전제가 라우팅에도 반영된다 — 전부 유지(중복)뿐이어도 Compose는
돌아 정상 요약을 쓰고, Impact만 건너뛴다. 반대로 팩트를 아예 못 뽑았으면(수집
실패) 요약을 쓸 재료 자체가 없으므로 예외를 올려 호출자가 기존 generate()로
되돌아가게 한다.
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
    captured: dict[str, Any] | None = None,
) -> None:
    """서브그래프의 LLM·DB 경계를 모두 대체한다.

    captured를 넘기면 compose·impact가 실제로 어떤 facts를 받았는지 기록한다
    (Compose는 전체, Impact는 하이라이트만 받는지 검증하는 데 쓴다).
    """
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
        if captured is not None:
            captured["compose_facts"] = kwargs.get("facts")
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
        if captured is not None:
            captured["impact_facts"] = kwargs.get("facts")
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


def test_compose_gets_every_fact_impact_gets_highlights_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compose는 유지 팩트까지 전체로 받고, Impact는 신규·갱신만 받는다.

    Compose가 쓰는 "핵심 요약·맥락"은 전체 그림을 그려야 하므로 유지(중복)
    팩트도 필요하지만, Impact의 "주목할 점"은 실제로 달라진 것에 대한
    해석이라 유지 팩트를 줄 이유가 없다.
    """
    order: list[str] = []
    stored: list[dict[str, Any]] = []
    captured: dict[str, Any] = {}
    _patch_graph(
        monkeypatch,
        order=order,
        stored=stored,
        diff_outcomes=[DiffOutcome(facts=(_fact("new"), _fact("duplicate")))],
        validations=[
            ValidationOutcome(
                facts=(
                    ValidatedFact(fact=_fact("new")),
                    ValidatedFact(fact=_fact("duplicate")),
                )
            )
        ],
        captured=captured,
    )

    _run()

    assert len(captured["compose_facts"]) == 2  # 신규 + 유지 전체
    assert len(captured["impact_facts"]) == 1  # 신규만
    assert captured["impact_facts"][0].verdict == "new"


def test_all_duplicates_run_compose_but_skip_impact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전부 유지(중복)여도 Compose는 돌려 정상 요약을 쓰고, Impact만 건너뛴다.

    "달라진 게 없다"가 "요약을 안 쓴다"는 뜻이 아니다 — 평소와 같은
    정보요약보고서는 그대로 나가고, 해석할 변화가 없는 Impact만 생략한다.
    """
    order: list[str] = []
    stored: list[dict[str, Any]] = []
    _patch_graph(
        monkeypatch,
        order=order,
        stored=stored,
        diff_outcomes=[DiffOutcome(facts=(_fact("duplicate"), _fact("duplicate")))],
        validations=[
            ValidationOutcome(
                facts=(
                    ValidatedFact(fact=_fact("duplicate")),
                    ValidatedFact(fact=_fact("duplicate")),
                )
            )
        ],
    )

    result = _run()

    assert order == ["diff", "compose", "validate", "store"]  # impact만 생략
    assert result["no_change"] is True
    assert result["fact_count"] == 0
    assert stored[0]["outcome"] == "no_change"
    assert stored[0]["duplicate_fact_count"] == 2
    assert stored[0]["facts"] == []  # 유지 팩트는 다시 저장하지 않는다
    # 요약 보고서 자체는 정상적으로 나간다 — 비어 있는 대체 문구가 아니다.
    assert "브리핑 [G1]" in result["generated"].body


def test_empty_facts_raises_so_the_caller_falls_back_to_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """오늘 자료에서 팩트를 하나도 못 뽑으면 요약을 쓸 재료가 없다.

    "달라진 게 없다"와는 다른 실패다 — 예외를 올려 상위 change_history 노드가
    기존 generate() 경로로 되돌아가게 한다.
    """
    order: list[str] = []
    stored: list[dict[str, Any]] = []
    _patch_graph(
        monkeypatch, order=order, stored=stored, diff_outcomes=[DiffOutcome(facts=())]
    )

    with pytest.raises(RuntimeError):
        _run()

    assert order == ["diff"]  # compose까지 가지 않는다


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


def test_no_change_report_still_runs_the_quality_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """달라진 점이 없어도 이제는 기존 품질 검사를 그대로 받는다.

    예전에는 이 경로가 "짧은 보고서"라 인용 없는 것이 정상이라 검사를
    건너뛰었다. 지금은 Compose가 유지 팩트로도 실제 요약을 쓰므로, 그 요약이
    품질 기준(길이·인용률)을 충족하는지 그대로 확인해야 한다.
    """
    order: list[str] = []
    stored: list[dict[str, Any]] = []
    _patch_graph(
        monkeypatch,
        order=order,
        stored=stored,
        diff_outcomes=[DiffOutcome(facts=(_fact("duplicate"),))],
        validations=[ValidationOutcome(facts=(ValidatedFact(fact=_fact("duplicate")),))],
    )

    result = _run()

    assert result["no_change"] is True
    assert result["quality_outcome"]  # 판정 자체는 실제로 수행됐다
    assert result["quality_outcome"] != "skipped_no_change"  # 더는 건너뛰지 않는다


def test_normal_report_runs_the_quality_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """팩트가 있는 보고서는 기존 품질 검사를 그대로 거친다."""
    order: list[str] = []
    stored: list[dict[str, Any]] = []
    _patch_graph(monkeypatch, order=order, stored=stored)

    result = _run()

    assert result["quality_outcome"]
    assert result["quality_outcome"] != "skipped_no_change"
