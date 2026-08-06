"""델타 보고서 조립(코드)의 섹션 구성과 Citation 처리를 검증한다.

이 단계는 LLM을 쓰지 않으므로 완전히 결정적이다. 확인하는 것은 네 섹션이 모두
나오는지, 갱신 팩트가 before/after로 대비되는지, 근거 목록에 없는 참조가
저장으로 새어 나가지 않는지다.
"""

from __future__ import annotations

from datetime import date

from agent.change_history.features.assembly import (
    CHANGED_SUBHEADING,
    IMPLICATIONS_HEADING,
    NEW_SUBHEADING,
    OVERVIEW_HEADING,
    TIMELINE_HEADING,
    UPDATES_HEADING,
    assemble_delta_report,
    collect_allowed_citations,
)
from agent.change_history.features.compose import ComposeOutcome
from agent.change_history.features.diff import DiffFact
from agent.change_history.features.impact import ImpactOutcome
from agent.change_history.features.validation import ValidatedFact
from shared.report_models import ReportContextDocument

REFERENCE_DATE = date(2026, 8, 5)


def _document(reference: str) -> ReportContextDocument:
    """테스트용 근거 문서를 만든다."""
    return ReportContextDocument(
        reference=reference,
        document_version_id=f"ver-{reference}",
        chunk_id=f"chunk-{reference}",
        namespace_key="global",
        title=f"{reference} 기사",
        content="본문",
        url=None,
        score=0.7,
    )


CONTEXTS = [_document("G1"), _document("P1")]


def _updated_item() -> ValidatedFact:
    """before 값이 채워진 갱신 팩트를 만든다."""
    return ValidatedFact(
        fact=DiffFact(
            verdict="updated",
            subject="B사 HBM4",
            attribute="양산 일정",
            fact_value="2026-3Q",
            today_statement="양산이 2026-3Q로 연기됐다.",
            updates_fact_id="fact-1",
            source_reference="G1",
        ),
        before_value="2026-2Q",
        occurred_on=date(2026, 8, 4),
        date_precision="day",
        timeline_description="연기 발표 [G1]",
    )


def _new_item() -> ValidatedFact:
    """신규 팩트를 만든다."""
    return ValidatedFact(
        fact=DiffFact(
            verdict="new",
            subject="A사 HBM4",
            attribute="가격",
            fact_value="10% 인상",
            today_statement="A사가 가격을 10% 올렸다.",
            source_reference="P1",
        ),
        occurred_on=date(2026, 8, 1),
        date_precision="quarter",
        timeline_description="가격 인상 [P1]",
    )


def _compose() -> ComposeOutcome:
    """Overview 생성 결과를 만든다."""
    return ComposeOutcome(
        title="반도체 변경점",
        summary="양산 일정이 밀렸습니다 [G1].",
        overview="어제까지는 2026-2Q였지만 오늘 연기가 확인됐습니다 [G1].",
    )


def _impact() -> ImpactOutcome:
    """파급효과 추론 결과를 만든다."""
    return ImpactOutcome(
        implications="공급 지연이 길어질 수 있습니다 [G1].",
        actions=("재고 확인",),
    )


def test_report_contains_all_four_sections() -> None:
    """조립 결과에 네 섹션이 모두 들어간다."""
    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        facts=[_updated_item(), _new_item()],
        compose=_compose(),
        impact=_impact(),
        contexts=CONTEXTS,
    )

    for heading in (
        OVERVIEW_HEADING,
        UPDATES_HEADING,
        TIMELINE_HEADING,
        IMPLICATIONS_HEADING,
    ):
        assert heading in content.body


def test_updated_fact_shows_before_and_after() -> None:
    """갱신 팩트는 before(DB 값)와 after(오늘 값)가 대비되게 적힌다."""
    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        facts=[_updated_item()],
        compose=_compose(),
        impact=_impact(),
        contexts=CONTEXTS,
    )

    assert "`2026-2Q` → `2026-3Q`" in content.body
    assert CHANGED_SUBHEADING in content.body


def test_changed_and_new_facts_go_into_separate_subsections() -> None:
    """달라진 사실과 새로 확인된 사실을 소제목으로 갈라 놓는다.

    한 목록에 섞으면 "무엇이 달라졌나"가 눈에 들어오지 않는다 — 이 보고서의
    존재 이유가 그것이므로 섹션부터 나눈다. 달라진 쪽을 먼저 보여준다.
    """
    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        facts=[_new_item(), _updated_item()],
        compose=_compose(),
        impact=_impact(),
        contexts=CONTEXTS,
    )

    body = content.body
    assert f"{CHANGED_SUBHEADING} (1건)" in body
    assert f"{NEW_SUBHEADING} (1건)" in body
    # 입력 순서와 무관하게 달라진 사실이 먼저 온다.
    assert body.index(CHANGED_SUBHEADING) < body.index(NEW_SUBHEADING)
    # 신규 팩트에는 이전 값이 없으므로 화살표 표기가 붙지 않는다.
    new_block = body[body.index(NEW_SUBHEADING) : body.index(TIMELINE_HEADING)]
    assert "→" not in new_block


def test_subsection_is_omitted_when_that_kind_has_no_fact() -> None:
    """한 종류만 있으면 빈 소제목을 만들지 않는다."""
    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        facts=[_new_item()],
        compose=_compose(),
        impact=_impact(),
        contexts=CONTEXTS,
    )

    assert NEW_SUBHEADING in content.body
    assert CHANGED_SUBHEADING not in content.body


def test_timeline_is_sorted_by_absolute_date() -> None:
    """타임라인은 절대 날짜 오름차순으로 정렬된다."""
    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        facts=[_updated_item(), _new_item()],
        compose=_compose(),
        impact=_impact(),
        contexts=CONTEXTS,
    )

    body = content.body
    assert body.index("2026-08-01") < body.index("2026-08-04")
    # 구간으로만 아는 날짜는 정밀도를 함께 표시한다.
    assert "(quarter)" in body


def test_citations_are_limited_to_available_references() -> None:
    """근거 목록에 없는 참조는 Citation에 넣지 않는다.

    저장(persist_report_generation)이 참조로 근거 문서를 찾으므로, 없는 참조가
    섞이면 저장이 깨진다.
    """
    body = "본문 [G1] 그리고 [G9] 그리고 [P1] 다시 [G1]"

    assert collect_allowed_citations(body, CONTEXTS) == ("G1", "P1")


def test_first_run_notice_is_stated_in_the_body() -> None:
    """최초 실행이면 비교 대상이 없다는 사실을 본문에 밝힌다."""
    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        facts=[_new_item()],
        compose=_compose(),
        impact=_impact(),
        contexts=CONTEXTS,
        is_first_run=True,
    )

    assert "최초 실행" in content.body


def test_no_change_report_still_has_every_section() -> None:
    """변화가 없어도 네 섹션 구조와 안내 문구를 유지한다."""
    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        facts=[],
        compose=ComposeOutcome(),
        impact=ImpactOutcome(),
        contexts=CONTEXTS,
        no_change=True,
    )

    assert "새로 확인된 변화가 없습니다" in content.body
    assert UPDATES_HEADING in content.body
    assert content.citation_references == ()
    # 제목·요약이 비어도 코드가 기본값을 채워 저장이 실패하지 않는다.
    assert content.title
    assert content.summary
