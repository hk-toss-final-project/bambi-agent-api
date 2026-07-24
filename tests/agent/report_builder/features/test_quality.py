"""리포트 품질 판정(quality) 검증. 순수 계산만 하며 LLM은 호출하지 않는다."""

from agent.report_builder.features import quality
from shared.report_models import GeneratedReportContent


def _content(body: str, *, refs: tuple[str, ...] = ()) -> GeneratedReportContent:
    """테스트용 생성 리포트를 만든다."""
    return GeneratedReportContent(
        title="제목", summary="요약", body=body, citation_references=refs
    )


def test_pass_when_body_cites_and_is_long_enough() -> None:
    """근거를 인용하고 충분히 길면 통과한다."""
    body = "코스피가 급락했다[P1]. 반도체 약세가 원인이다[G2]. " + "상세 분석. " * 40
    verdict = quality.evaluate_report(_content(body, refs=("P1", "G2")), context_count=3)

    assert verdict.outcome == quality.PASS
    assert verdict.should_regenerate is False
    assert verdict.correction == ""


def test_no_citations_triggers_regeneration() -> None:
    """본문이 근거를 하나도 인용하지 않으면 재생성 대상이다."""
    body = "코스피가 급락했다. 원인은 반도체 약세다. " * 20  # 길지만 인용 없음
    verdict = quality.evaluate_report(_content(body), context_count=5)

    assert verdict.outcome == quality.NO_CITATIONS
    assert verdict.should_regenerate is True
    assert "인용" in verdict.correction        # 교정 지시가 있다


def test_too_short_triggers_regeneration() -> None:
    """본문이 최소 길이에 못 미치면 재생성 대상이다."""
    verdict = quality.evaluate_report(_content("짧음[P1]."), context_count=3)

    assert verdict.outcome == quality.TOO_SHORT
    assert verdict.should_regenerate is True


def test_ignores_context_triggers_regeneration() -> None:
    """근거를 많이 줬는데 인용률이 하한 미만이면 재생성 대상이다."""
    # 근거 10개를 줬는데 1개만 인용 → 인용률 0.1 < 0.3
    body = "코스피 분석[P1]. " + "충분히 긴 본문 내용입니다. " * 30
    verdict = quality.evaluate_report(_content(body, refs=("P1",)), context_count=10)

    assert verdict.outcome == quality.IGNORES_CONTEXT
    assert verdict.should_regenerate is True


def test_low_context_count_skips_coverage_check() -> None:
    """근거가 애초에 적었으면(검색 문제) 인용률 검사를 건너뛴다.

    근거 2개 중 1개만 인용해도(0.5) 통과. 근거 부족은 재생성으로 못 고치기 때문이다.
    """
    body = "코스피 분석[P1]. " + "충분히 긴 본문 내용입니다. " * 30
    verdict = quality.evaluate_report(_content(body, refs=("P1",)), context_count=2)

    assert verdict.outcome == quality.PASS


def test_zero_context_does_not_divide_by_zero() -> None:
    """근거가 0개여도 인용률 계산에서 0으로 나누지 않는다."""
    body = "개념 정리[P1]. " + "충분히 긴 본문 내용입니다. " * 30
    verdict = quality.evaluate_report(_content(body, refs=("P1",)), context_count=0)

    assert verdict.outcome == quality.PASS


def test_citation_refs_field_counts_even_without_inline_markup() -> None:
    """본문에 [P1] 표기가 없어도 citation_references가 있으면 인용 0개로 보지 않는다."""
    body = "근거를 반영한 충분히 긴 본문입니다. " * 20  # 인라인 표기는 없음
    verdict = quality.evaluate_report(_content(body, refs=("P1", "G1")), context_count=3)

    # 인용 0개(NO_CITATIONS)로 걸리지 않는다. (coverage 검사는 인라인 기준이라 별개)
    assert verdict.outcome != quality.NO_CITATIONS


def test_check_order_no_citations_beats_too_short() -> None:
    """인용 0개와 너무 짧음을 동시에 만족하면 인용 0개가 먼저 잡힌다."""
    verdict = quality.evaluate_report(_content("짧고 인용 없음."), context_count=3)

    assert verdict.outcome == quality.NO_CITATIONS


def test_regeneratable_set_excludes_pass() -> None:
    """PASS는 재생성 대상이 아니다 (회귀 방지)."""
    assert quality.PASS not in quality.REGENERATABLE
    assert quality.NO_CITATIONS in quality.REGENERATABLE
