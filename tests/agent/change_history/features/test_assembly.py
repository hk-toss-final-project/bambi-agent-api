"""델타 보고서 조립(코드)의 섹션 구성과 Citation 처리를 검증한다.

이 단계는 LLM을 쓰지 않으므로 완전히 결정적이다. 이 보고서는 "달라진 것만"
보여주는 문서가 아니라 평소 요약 보고서 + 달라진 점 하이라이트라, 확인하는 것도
그에 맞춘다 — 핵심 요약은 달라진 점이 없어도 항상 채워지는지, "이번에 달라진
점"에는 신규·갱신만 들어가는지, 타임라인은 확정 날짜가 있을 때만 나오는지,
근거 목록에 없는 참조가 저장으로 새어 나가지 않는지, 이모지가 섞이지 않는지다.
"""

from __future__ import annotations

from datetime import date

from agent.change_history.features.assembly import (
    CHANGED_SUBHEADING,
    IMPLICATIONS_HEADING,
    NEW_SUBHEADING,
    NO_CHANGE_NOTICE,
    NO_WATCH_ITEMS_NOTICE,
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
    """핵심 요약 생성 결과를 만든다."""
    return ComposeOutcome(
        title="반도체 요약",
        summary="양산 일정이 밀렸습니다 [G1].",
        overview="B사는 여전히 HBM4를 개발 중이며 [P1], 양산 시점이 밀렸습니다 [G1].",
    )


def _impact() -> ImpactOutcome:
    """파급효과 추론 결과를 만든다."""
    return ImpactOutcome(
        implications="공급 지연이 길어질 수 있습니다 [G1].",
        actions=("재고 확인",),
    )


def test_report_has_the_four_sections_in_order() -> None:
    """조립 결과는 달라진 점 → 핵심 요약 → 주목할 점 → 타임라인 순서로 나온다."""
    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        highlight_facts=[_updated_item(), _new_item()],
        compose=_compose(),
        impact=_impact(),
        contexts=CONTEXTS,
    )

    body = content.body
    for heading in (
        UPDATES_HEADING,
        OVERVIEW_HEADING,
        IMPLICATIONS_HEADING,
        TIMELINE_HEADING,
    ):
        assert heading in body
    assert (
        body.index(UPDATES_HEADING)
        < body.index(OVERVIEW_HEADING)
        < body.index(IMPLICATIONS_HEADING)
        < body.index(TIMELINE_HEADING)
    )


def test_no_heading_or_body_text_contains_emoji() -> None:
    """이모지·장식 기호가 섞이지 않는다(요청한 폼 형식의 핵심 조건)."""
    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        highlight_facts=[_updated_item(), _new_item()],
        compose=_compose(),
        impact=_impact(),
        contexts=CONTEXTS,
    )

    for char in content.body:
        assert ord(char) < 0x1F000, f"이모지로 보이는 문자가 있습니다: {char!r}"


def test_updated_fact_shows_before_and_after() -> None:
    """갱신 팩트는 before(DB 값 취소선)와 after(오늘 값 문장)가 대비되게 적힌다."""
    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        highlight_facts=[_updated_item()],
        compose=_compose(),
        impact=_impact(),
        contexts=CONTEXTS,
    )

    assert "(기존) ~~2026-2Q~~" in content.body
    assert "(변경)" in content.body
    assert "양산이 2026-3Q로 연기됐다." in content.body
    assert CHANGED_SUBHEADING in content.body


def test_changed_and_new_facts_go_into_separate_subsections() -> None:
    """달라진 사실과 새로 확인된 사실을 소제목으로 갈라 놓는다.

    한 목록에 섞으면 "무엇이 달라졌나"가 눈에 들어오지 않는다. 달라진 쪽을
    먼저 보여준다.
    """
    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        highlight_facts=[_new_item(), _updated_item()],
        compose=_compose(),
        impact=_impact(),
        contexts=CONTEXTS,
    )

    body = content.body
    assert f"{CHANGED_SUBHEADING} (1건)" in body
    assert f"{NEW_SUBHEADING} (1건)" in body
    assert body.index(CHANGED_SUBHEADING) < body.index(NEW_SUBHEADING)
    updates_section = body[body.index(UPDATES_HEADING) : body.index(OVERVIEW_HEADING)]
    new_block = updates_section[updates_section.index(NEW_SUBHEADING) :]
    assert "→" not in new_block


def test_subsection_is_omitted_when_that_kind_has_no_fact() -> None:
    """한 종류만 있으면 빈 소제목을 만들지 않는다."""
    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        highlight_facts=[_new_item()],
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
        highlight_facts=[_updated_item(), _new_item()],
        compose=_compose(),
        impact=_impact(),
        contexts=CONTEXTS,
    )

    body = content.body
    assert body.index("2026-08-01") < body.index("2026-08-04")
    # 구간으로만 아는 날짜는 정밀도를 함께 표시한다.
    assert "(quarter)" in body


def test_timeline_section_is_omitted_when_no_dated_item_exists() -> None:
    """확정 가능한 날짜가 없으면 타임라인 섹션 자체를 뺀다.

    빈 자리표시 문구를 남기지 않는다 — 폼 형식이 요구한 "숨김" 동작이다.
    """
    undated = ValidatedFact(
        fact=DiffFact(
            verdict="new",
            subject="C사 HBM4",
            attribute="공급 계획",
            fact_value="확대 검토",
            today_statement="C사가 공급 확대를 검토 중이다.",
            source_reference="G1",
        )
    )

    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        highlight_facts=[undated],
        compose=_compose(),
        impact=_impact(),
        contexts=CONTEXTS,
    )

    assert TIMELINE_HEADING not in content.body


def test_citations_are_limited_to_available_references() -> None:
    """근거 목록에 없는 참조는 Citation에 넣지 않는다.

    저장(persist_report_generation)이 참조로 근거 문서를 찾으므로, 없는 참조가
    섞이면 저장이 깨진다.
    """
    body = "본문 [G1] 그리고 [G9] 그리고 [P1] 다시 [G1]"

    assert collect_allowed_citations(body, CONTEXTS) == ("G1", "P1")


def test_first_run_does_not_add_a_meta_notice_to_the_body() -> None:
    """조립 결과에 "비교 대상이 없다" 같은 메타 코멘트가 없다.

    2026-08-12 사용자 피드백: 이런 문구가 불친절하게 읽힌다. is_first_run
    여부는 store 단계에서 DB 저장·집계용 상태로만 쓰이고, 조립(assembly)은
    그 값을 아예 받지 않는다 — 첫 실행이든 아니든 같은 형태로 조립된다.
    """
    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        highlight_facts=[_new_item()],
        compose=_compose(),
        impact=_impact(),
        contexts=CONTEXTS,
    )

    assert "최초 실행" not in content.body
    assert "비교 대상" not in content.body


def test_no_highlight_facts_still_produces_a_full_summary_report() -> None:
    """달라진 점이 없어도 핵심 요약·주목할 점은 정상적으로 채워진다.

    이 보고서는 "달라진 것만" 보여주는 문서가 아니라 평소 요약 보고서다.
    Compose·Impact가 실제로 돌았다는 전제로, 그 결과가 그대로 나가는지 본다.
    """
    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        highlight_facts=[],
        compose=_compose(),
        impact=ImpactOutcome(),  # 달라진 게 없으면 Impact는 돌지 않는다
        contexts=CONTEXTS,
    )

    body = content.body
    assert NO_CHANGE_NOTICE in body
    assert NO_WATCH_ITEMS_NOTICE in body
    # 핵심 요약은 Compose가 실제로 쓴 전체 맥락 문단 그대로다 — 짧아지지 않는다.
    assert _compose().overview in body
    # overview가 인용한 참조가 등장 순서대로 남는다(유지 팩트 인용 포함).
    # overview 원문은 "...[P1]... [G1]." 순이라 P1이 먼저다.
    assert content.citation_references == ("P1", "G1")
    # 제목·요약이 비어도 코드가 기본값을 채워 저장이 실패하지 않는다.
    assert content.title
    assert content.summary
    # 제목·요약은 구조화 필드로만 나가고 본문에는 중복으로 박히지 않는다 —
    # 카드 헤더와 본문 양쪽에 같은 제목이 두 번 보이는 걸 막기 위함이다.
    assert content.title not in body
    assert content.summary not in body


def test_title_and_summary_come_from_compose() -> None:
    """카드 제목·한 줄 결론은 Compose가 쓴 값을 그대로 쓴다.

    이 보고서는 평소 요약 보고서와 같은 자리에 나가므로, "달라진 점 몇 건"이
    아니라 실제 결론이 카드 제목·미리보기에 보여야 한다.
    """
    content = assemble_delta_report(
        topic="반도체",
        reference_date=REFERENCE_DATE,
        highlight_facts=[_updated_item()],
        compose=_compose(),
        impact=_impact(),
        contexts=CONTEXTS,
    )

    assert content.title == "반도체 요약"
    assert content.summary == "양산 일정이 밀렸습니다 [G1]."


def test_fresh_facts_capped_at_five() -> None:
    """새로 확인된 사실이 15개 남발되지 않고 최대 5개로 제한되는지 검증한다."""
    many_fresh = [
        ValidatedFact(fact=DiffFact(subject=f"주제{i}", attribute=f"속성{i}", fact_value=f"값{i}", today_statement=f"새로운 사실 {i}", verdict="new"))
        for i in range(15)
    ]
    content = assemble_delta_report(
        topic="테스트",
        reference_date=REFERENCE_DATE,
        highlight_facts=many_fresh,
        compose=_compose(),
        impact=_impact(),
        contexts=CONTEXTS,
    )
    assert f"{NEW_SUBHEADING} (5건)" in content.body
    assert "새로운 사실 4" in content.body
    assert "새로운 사실 5" not in content.body
