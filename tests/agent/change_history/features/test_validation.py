"""델타 정합성 검증(팩트 ID 실재·소속, 날짜 타당성, 인용 마커)을 검증한다.

Critic이 구조적으로 볼 수 없는 사각지대만 다루는 코드 검증이라, LLM 없이
결정적으로 돌아야 한다. DB 조회만 대체한다.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import pytest

from agent.change_history.features import validation as validation_module
from agent.change_history.features.compose import TimelineDraft
from agent.change_history.features.dates import (
    is_plausible_date,
    normalize_precision,
    parse_absolute_date,
)
from agent.change_history.features.diff import DiffFact
from agent.change_history.features.validation import (
    COMPOSE_WORKER,
    DIFF_WORKER,
    IMPACT_WORKER,
    validate_delta_outputs,
)
from shared.change_history_models import ChangeHistoryFact

REFERENCE_DATE = date(2026, 8, 5)


class _FakeConnection:
    """transaction 문맥만 제공하는 Connection Test Double."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """빈 Transaction 문맥을 제공한다."""
        yield


def _updated_fact(fact_id: str | None) -> DiffFact:
    """갱신 판정을 받은 팩트를 만든다."""
    return DiffFact(
        verdict="updated",
        subject="B사 HBM4",
        attribute="양산 일정",
        fact_value="2026-3Q",
        today_statement="양산이 2026-3Q로 연기됐다.",
        updates_fact_id=fact_id,
        source_reference="G1",
    )


def _new_fact() -> DiffFact:
    """신규 판정을 받은 팩트를 만든다."""
    return DiffFact(
        verdict="new",
        subject="A사 HBM4",
        attribute="가격",
        fact_value="10% 인상",
        today_statement="A사가 가격을 10% 올렸다.",
        source_reference="G1",
    )


def _patch_base(
    monkeypatch: pytest.MonkeyPatch, facts: dict[str, ChangeHistoryFact]
) -> None:
    """DB의 과거 팩트 조회를 고정 사전으로 대체한다."""

    async def fake_load(connection: Any, **kwargs: Any) -> dict[str, ChangeHistoryFact]:
        """지정한 팩트만 존재하는 DB를 흉내낸다."""
        return {
            fact_id: fact
            for fact_id, fact in facts.items()
            if fact_id in set(kwargs["fact_ids"])
        }

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """RLS Scope 설정을 생략한다."""

    monkeypatch.setattr(validation_module, "load_change_history_facts_by_ids", fake_load)
    monkeypatch.setattr(validation_module, "set_personal_wiki_scope", fake_scope)


def _run(
    facts: list[DiffFact], timeline: list[TimelineDraft]
) -> validation_module.ValidationOutcome:
    """검증을 고정 입력으로 실행한다."""
    return asyncio.run(
        validate_delta_outputs(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
            facts=facts,
            timeline=timeline,
            reference_date=REFERENCE_DATE,
        )
    )


def test_missing_fact_id_is_filtered_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB에 없는 갱신 대상 ID를 가리킨 팩트는 통과시키지 않는다."""
    _patch_base(monkeypatch, {})

    outcome = _run([_updated_fact("존재하지-않는-id")], [])

    assert outcome.facts == ()
    assert [problem.reason for problem in outcome.problems] == [
        "updates_fact_id_not_found"
    ]
    assert outcome.failed_workers == frozenset({DIFF_WORKER})


def test_before_value_comes_from_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """before 값은 LLM이 아니라 DB에서 읽은 과거 팩트에서 온다."""
    _patch_base(
        monkeypatch,
        {
            "fact-1": ChangeHistoryFact(
                fact_id="fact-1",
                subject="B사 HBM4",
                attribute="양산 일정",
                fact_value="2026-2Q",
                statement="B사 HBM4 양산은 2026-2Q다.",
                verdict="new",
            )
        },
    )

    outcome = _run([_updated_fact("fact-1")], [])

    assert outcome.problems == ()
    assert outcome.facts[0].before_value == "2026-2Q"


def test_out_of_range_timeline_date_is_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """기준일에서 지나치게 먼 날짜는 타임라인에서 빼고 팩트는 살린다."""
    _patch_base(monkeypatch, {})

    outcome = _run(
        [_new_fact()],
        [
            TimelineDraft(
                fact_index=0,
                raw_date="2099-01-01",
                precision="day",
                description="먼 미래 [G1]",
            )
        ],
    )

    assert outcome.facts[0].occurred_on is None
    assert outcome.facts[0].timeline_description == ""
    assert [problem.reason for problem in outcome.problems] == [
        "timeline_date_out_of_range"
    ]
    assert outcome.failed_workers == frozenset({COMPOSE_WORKER})


def test_valid_timeline_date_is_attached_to_the_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """타당한 절대 날짜는 해당 팩트에 붙어 저장·표시에 함께 쓰인다."""
    _patch_base(monkeypatch, {})

    outcome = _run(
        [_new_fact()],
        [
            TimelineDraft(
                fact_index=0,
                raw_date="2026-08-01",
                precision="day",
                description="가격 인상 발표 [G1]",
            )
        ],
    )

    assert outcome.problems == ()
    assert outcome.facts[0].occurred_on == date(2026, 8, 1)
    assert outcome.facts[0].timeline_description == "가격 인상 발표 [G1]"


def test_timeline_pointing_at_unknown_fact_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """없는 팩트 순번을 가리킨 타임라인 항목은 Compose 문제로 기록한다."""
    _patch_base(monkeypatch, {})

    outcome = _run(
        [_new_fact()],
        [TimelineDraft(fact_index=7, raw_date="2026-08-01", precision="day", description="x")],
    )

    assert [problem.reason for problem in outcome.problems] == [
        "timeline_fact_index_missing"
    ]


def test_date_helpers_normalize_and_bound_values() -> None:
    """날짜 파서와 범위 판정이 규칙대로 동작한다."""
    assert parse_absolute_date("2026-08-05") == date(2026, 8, 5)
    assert parse_absolute_date("2026년 8월") is None
    assert parse_absolute_date("") is None
    assert normalize_precision("QUARTER") == "quarter"
    assert normalize_precision("반기") == "unknown"
    assert is_plausible_date(date(2026, 8, 6), reference_date=REFERENCE_DATE)
    assert is_plausible_date(date(2024, 1, 1), reference_date=REFERENCE_DATE)
    assert not is_plausible_date(date(2015, 1, 1), reference_date=REFERENCE_DATE)
    assert not is_plausible_date(date(2035, 1, 1), reference_date=REFERENCE_DATE)


def test_overview_without_citation_marker_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """인용 마커 없는 Overview는 Compose 문제로 기록한다.

    Critic은 마커를 찾아 원문과 대조하는 방식으로만 검증하므로, 마커가 없으면
    그 섹션은 검토를 통과해도 아무것도 확인되지 않은 것이다.
    """
    _patch_base(monkeypatch, {})

    outcome = asyncio.run(
        validate_delta_outputs(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
            facts=[_new_fact()],
            timeline=[],
            reference_date=REFERENCE_DATE,
            overview="가격이 올랐습니다.",
            implications="원가 부담이 커집니다 [G1].",
        )
    )

    assert [problem.reason for problem in outcome.problems] == [
        "overview_missing_citation"
    ]
    assert outcome.failed_workers == frozenset({COMPOSE_WORKER})
    # 팩트 자체는 살아 있다 — 다시 쓰게 할 뿐 내용을 버리지 않는다.
    assert len(outcome.facts) == 1


def test_implications_without_citation_marker_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """인용 마커 없는 파급효과 서술은 Impact 문제로 기록한다."""
    _patch_base(monkeypatch, {})

    outcome = asyncio.run(
        validate_delta_outputs(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
            facts=[_new_fact()],
            timeline=[],
            reference_date=REFERENCE_DATE,
            overview="가격이 올랐습니다 [G1].",
            implications="원가 부담이 커집니다.",
        )
    )

    assert [problem.reason for problem in outcome.problems] == [
        "implications_missing_citation"
    ]
    assert outcome.failed_workers == frozenset({IMPACT_WORKER})


def test_citation_check_ignores_references_that_do_not_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """근거 목록에 없는 참조는 마커로 세지 않는다(Critic이 원문을 못 꺼낸다)."""
    _patch_base(monkeypatch, {})

    outcome = asyncio.run(
        validate_delta_outputs(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
            facts=[_new_fact()],  # source_reference="G1"
            timeline=[],
            reference_date=REFERENCE_DATE,
            overview="가격이 올랐습니다 [G9].",
            implications="원가 부담이 커집니다 [G1].",
        )
    )

    assert [problem.reason for problem in outcome.problems] == [
        "overview_missing_citation"
    ]


def test_citation_check_is_skipped_when_no_fact_has_a_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """인용할 근거가 애초에 없으면 마커를 요구하지 않는다.

    다시 시켜도 없는 마커가 생기지 않으므로, 요구하면 헛재작업만 늘어난다.
    """
    _patch_base(monkeypatch, {})
    fact = DiffFact(
        verdict="new",
        subject="A사",
        attribute="가격",
        fact_value="인상",
        today_statement="가격을 올렸다.",
        source_reference="",
    )

    outcome = asyncio.run(
        validate_delta_outputs(
            _FakeConnection(),  # type: ignore[arg-type]
            user_id="user-1",
            topic="반도체",
            facts=[fact],
            timeline=[],
            reference_date=REFERENCE_DATE,
            overview="가격이 올랐습니다.",
            implications="원가 부담이 커집니다.",
        )
    )

    assert outcome.problems == ()


def test_has_valid_citation_matches_only_available_references() -> None:
    """마커 검사는 실제 근거 목록과 대조한다."""
    assert validation_module.has_valid_citation("본문 [G1]", ["G1", "P2"])
    assert not validation_module.has_valid_citation("본문 [G9]", ["G1"])
    assert not validation_module.has_valid_citation("마커 없는 본문", ["G1"])


def test_updated_fact_with_same_value_is_filtered_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """과거 값과 오늘 값이 동일한 updated 팩트는 보고서에서 걸러낸다."""
    _patch_base(
        monkeypatch,
        {
            "fact-1": ChangeHistoryFact(
                fact_id="fact-1",
                subject="B사 HBM4",
                attribute="양산 일정",
                fact_value="2026-3Q",
                statement="B사 HBM4 양산은 2026-3Q다.",
                verdict="new",
            )
        },
    )

    outcome = _run([_updated_fact("fact-1")], [])

    assert outcome.facts == ()
    assert [problem.reason for problem in outcome.problems] == [
        "updated_value_unchanged"
    ]
    assert outcome.failed_workers == frozenset({DIFF_WORKER})

