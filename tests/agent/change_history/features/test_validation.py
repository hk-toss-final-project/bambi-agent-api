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
    monkeypatch: pytest.MonkeyPatch,
    facts: dict[str, ChangeHistoryFact],
    *,
    active: list[ChangeHistoryFact] | None = None,
) -> None:
    """DB의 과거 팩트 조회를 고정 사전으로 대체한다.

    Args:
        monkeypatch: 조회 함수를 대체할 fixture
        facts: ID로 조회될 과거 팩트
        active: (subject, attribute) 매칭에 쓰일 활성 과거 팩트. 생략하면
            `facts`에 담긴 것이 곧 활성 팩트다.
    """
    active_facts = list(facts.values()) if active is None else active

    async def fake_load(connection: Any, **kwargs: Any) -> dict[str, ChangeHistoryFact]:
        """지정한 팩트만 존재하는 DB를 흉내낸다."""
        return {
            fact_id: fact
            for fact_id, fact in facts.items()
            if fact_id in set(kwargs["fact_ids"])
        }

    async def fake_list(connection: Any, **kwargs: Any) -> list[ChangeHistoryFact]:
        """활성 과거 팩트 목록 조회를 흉내낸다."""
        return list(active_facts)

    async def fake_scope(connection: Any, *, user_id: str) -> None:
        """RLS Scope 설정을 생략한다."""

    monkeypatch.setattr(validation_module, "load_change_history_facts_by_ids", fake_load)
    monkeypatch.setattr(validation_module, "list_change_history_facts", fake_list)
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
    # 코드가 이미 duplicate로 결론을 냈으므로 워커 재작업을 유발하지 않는다.
    assert outcome.failed_workers == frozenset()


def test_restated_updated_fact_is_filtered_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """조사만 붙은 재서술은 걸러낸다 (2026-08-11 운영 DB 실측 오탐)."""
    _patch_base(
        monkeypatch,
        {
            "fact-1": ChangeHistoryFact(
                fact_id="fact-1",
                subject="로또",
                attribute="미수령 당첨금 자동 지급 시스템",
                fact_value="오는 18일부터 시행된다.",
                statement="로또 미수령 당첨금 자동 지급 시스템이 18일부터 시행된다.",
                verdict="new",
            )
        },
    )
    restated = DiffFact(
        verdict="updated",
        subject="로또",
        attribute="미수령 당첨금 자동 지급 시스템",
        fact_value="18일부터 시행된다.",
        today_statement="로또 당첨금 자동 입금 시스템이 오는 18일부터 시행된다.",
        updates_fact_id="fact-1",
        source_reference="G1",
    )

    outcome = _run([restated], [])

    assert outcome.facts == ()
    assert [problem.reason for problem in outcome.problems] == [
        "updated_value_unchanged"
    ]
    # 재서술 억제가 diff·compose·impact 재작업을 유발하면 안 된다(호출 3회 낭비).
    assert outcome.failed_workers == frozenset()


def test_updated_fact_with_changed_number_still_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """수치가 실제로 달라진 갱신은 억제하지 않는다."""
    _patch_base(
        monkeypatch,
        {
            "fact-1": ChangeHistoryFact(
                fact_id="fact-1",
                subject="로또",
                attribute="미수령 당첨금 자동 지급 시스템",
                fact_value="오는 18일부터 시행된다.",
                statement="로또 미수령 당첨금 자동 지급 시스템이 18일부터 시행된다.",
                verdict="new",
            )
        },
    )
    changed = DiffFact(
        verdict="updated",
        subject="로또",
        attribute="미수령 당첨금 자동 지급 시스템",
        fact_value="오는 25일부터 시행된다.",
        today_statement="로또 당첨금 자동 입금 시스템이 25일로 미뤄졌다.",
        updates_fact_id="fact-1",
        source_reference="G1",
    )

    outcome = _run([changed], [])

    assert len(outcome.facts) == 1
    assert outcome.facts[0].before_value == "오는 18일부터 시행된다."
    assert outcome.problems == ()


def test_attribute_with_drifting_value_is_reported_but_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """회차가 박힌 이름표는 재작업 대상으로 알리되 팩트는 버리지 않는다."""
    _patch_base(monkeypatch, {})
    fact = DiffFact(
        verdict="new",
        subject="로또",
        attribute="제1237회",
        fact_value="1등 당첨번호가 발표됐다.",
        today_statement="로또 제1237회 1등 당첨번호가 발표됐다.",
        source_reference="G1",
    )

    outcome = _run([fact], [])

    # 내용은 멀쩡하므로 살린다 — 이름표만 다시 붙이면 된다.
    assert len(outcome.facts) == 1
    assert [problem.reason for problem in outcome.problems] == [
        "attribute_contains_drifting_value"
    ]
    assert outcome.failed_workers == frozenset({DIFF_WORKER})


def test_new_fact_matching_a_past_label_is_promoted_to_updated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """과거와 같은 (subject, attribute)인데 new로 찍힌 팩트를 갱신으로 되돌린다.

    2026-08-11 실측: diff worker가 코스닥/등락률 과거 값을 도구로 받아 놓고도
    오늘 값을 updates_fact_id 없이 new로 찍어, 변화가 사용자에게 안 보였다.
    """
    base = ChangeHistoryFact(
        fact_id="fact-1",
        subject="코스닥",
        attribute="등락률",
        fact_value="3거래일 만에 21% 급등",
        statement="코스닥 지수가 3거래일 만에 21% 급등했다.",
        verdict="new",
    )
    _patch_base(monkeypatch, {"fact-1": base})
    mislabeled = DiffFact(
        verdict="new",
        subject="코스닥",
        attribute="등락률",
        fact_value="5거래일 만에 30% 넘게 상승",
        today_statement="코스닥 지수가 5거래일 만에 30% 넘게 뛰었다.",
        source_reference="G1",
    )

    outcome = _run([mislabeled], [])

    assert len(outcome.facts) == 1
    assert outcome.facts[0].fact.verdict == "updated"
    assert outcome.facts[0].fact.updates_fact_id == "fact-1"
    assert outcome.facts[0].before_value == "3거래일 만에 21% 급등"
    assert outcome.problems == ()


def test_promoted_fact_with_unchanged_value_is_then_filtered_as_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """승격된 팩트의 값이 그대로면 이어지는 재서술 억제가 걸러낸다.

    승격이 없으면 같은 사실이 매번 새 소식으로 쌓인다. 승격만 하고 억제가 안
    걸리면 이번엔 거짓 변경으로 나간다. 두 검사가 이어져야 옳다.
    """
    base = ChangeHistoryFact(
        fact_id="fact-1",
        subject="로또",
        attribute="미수령 당첨금 자동 지급 시스템",
        fact_value="18일부터 시행된다.",
        statement="로또 미수령 당첨금 자동 지급 시스템이 18일부터 시행된다.",
        verdict="new",
    )
    _patch_base(monkeypatch, {"fact-1": base})
    restated_as_new = DiffFact(
        verdict="new",
        subject="로또",
        attribute="미수령 당첨금 자동 지급 시스템",
        fact_value="오는 18일부터 시행된다.",
        today_statement="로또 당첨금 자동 지급이 오는 18일부터 시행된다.",
        source_reference="G1",
    )

    outcome = _run([restated_as_new], [])

    assert outcome.facts == ()
    assert [problem.reason for problem in outcome.problems] == [
        "updated_value_unchanged"
    ]


def test_new_fact_without_a_matching_label_stays_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """과거에 같은 이름표가 없으면 그대로 신규다(엉뚱한 갱신을 만들지 않는다)."""
    base = ChangeHistoryFact(
        fact_id="fact-1",
        subject="로또",
        attribute="미수령 당첨금 자동 지급 시스템",
        fact_value="18일부터 시행된다.",
        statement="로또 미수령 당첨금 자동 지급 시스템이 18일부터 시행된다.",
        verdict="new",
    )
    _patch_base(monkeypatch, {"fact-1": base})
    unrelated = DiffFact(
        verdict="new",
        subject="로또",
        attribute="판매점 수수료율",
        fact_value="5%에서 5.5%로 인상",
        today_statement="복권 판매점 수수료율이 5%에서 5.5%로 오른다.",
        source_reference="G1",
    )

    outcome = _run([unrelated], [])

    assert len(outcome.facts) == 1
    assert outcome.facts[0].fact.verdict == "new"
    assert outcome.facts[0].fact.updates_fact_id is None


def test_promotion_matches_labels_case_and_space_insensitively() -> None:
    """대소문자·앞뒤 공백만 흡수하고, 뜻이 다른 이름표는 잇지 않는다."""
    base = ChangeHistoryFact(
        fact_id="fact-1",
        subject="B사 HBM4",
        attribute="양산 일정",
        fact_value="2026년 2분기",
        statement="B사 HBM4 양산 일정은 2026년 2분기다.",
        verdict="new",
    )
    spaced = DiffFact(
        verdict="new",
        subject="  B사 HBM4 ",
        attribute="양산 일정 ",
        fact_value="2026년 3분기",
        today_statement="양산이 2026년 3분기로 밀렸다.",
    )
    different = DiffFact(
        verdict="new",
        subject="B사 HBM4",
        attribute="생산 개시 시점",
        fact_value="2026년 3분기",
        today_statement="생산 개시가 2026년 3분기다.",
    )

    promoted, count = validation_module.promote_mislabeled_new_facts(
        [spaced, different], [base]
    )

    assert count == 1
    assert promoted[0].verdict == "updated"
    assert promoted[0].updates_fact_id == "fact-1"
    # 뜻은 같아도 표현이 다른 이름표까지 코드가 잇지는 않는다 — LLM의 몫이다.
    assert promoted[1].verdict == "new"


def test_stable_attribute_is_not_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """정상 이름표는 문제로 잡지 않는다(불필요한 재작업 방지)."""
    _patch_base(monkeypatch, {})

    outcome = _run([_new_fact()], [])

    assert outcome.problems == ()
    assert outcome.failed_workers == frozenset()

