"""주제별 델타 보고서를 한 장으로 합치는 조립을 검증한다.

여러 주제를 묶는 요청(아침 브리핑)은 주제마다 델타를 따로 돌린다. 합치는 단계는
LLM을 쓰지 않는 문자열 조작이라 완전히 결정적이다.
"""

from __future__ import annotations

from datetime import date

import pytest

from agent.change_history.api import merge_topic_delta_reports
from shared.report_models import GeneratedReportContent

REFERENCE_DATE = date(2026, 8, 11)


def _report(
    topic: str, *, citations: tuple[str, ...], tags: tuple[str, ...] = ()
) -> GeneratedReportContent:
    """주제 하나의 델타 보고서를 흉내낸다."""
    return GeneratedReportContent(
        title=f"{topic} 변경점",
        summary=f"{topic} 요약",
        body=(
            f"## Overview\n\n{topic} 브리핑 [{citations[0]}]\n\n"
            "## 🔥 주요 업데이트\n\n### 🆕 새로 확인된 사실 (1건)"
        ),
        citation_references=citations,
        content_tags=tags,
    )


def test_merged_body_separates_topics_and_demotes_section_headings() -> None:
    """주제는 ##로 갈리고 각 보고서의 섹션은 한 단계씩 내려간다.

    그대로 이어 붙이면 주제 구분과 섹션 구분이 같은 단계가 돼, 어디부터 다른
    주제인지 읽을 수 없다.
    """
    merged = merge_topic_delta_reports(
        [
            ("반도체", _report("반도체", citations=("G1",))),
            ("환율", _report("환율", citations=("G2",))),
        ],
        topic="오늘의 브리핑",
        reference_date=REFERENCE_DATE,
    )

    assert "## 반도체" in merged.body
    assert "## 환율" in merged.body
    assert "### Overview" in merged.body  # ## → ###
    assert "#### 🆕 새로 확인된 사실 (1건)" in merged.body  # ### → ####
    assert "\n## Overview" not in merged.body
    assert merged.body.index("## 반도체") < merged.body.index("## 환율")


def test_merged_citations_and_tags_are_unioned_without_duplicates() -> None:
    """인용 참조와 태그는 순서를 지키며 합집합으로 모은다.

    저장(persist)이 참조를 근거 문서에서 찾으므로, 여기서 빠뜨리면 인용이
    사라지고 중복이 남으면 같은 Citation Row를 두 번 만들려 한다.
    """
    merged = merge_topic_delta_reports(
        [
            ("반도체", _report("반도체", citations=("G1", "G2"), tags=("HBM",))),
            ("환율", _report("환율", citations=("G2", "G3"), tags=("HBM", "달러"))),
        ],
        topic="오늘의 브리핑",
        reference_date=REFERENCE_DATE,
    )

    assert merged.citation_references == ("G1", "G2", "G3")
    assert merged.content_tags == ("HBM", "달러")


def test_merged_summary_lists_each_topic() -> None:
    """카드 요약은 주제별 요약을 한 줄씩 담는다."""
    merged = merge_topic_delta_reports(
        [
            ("반도체", _report("반도체", citations=("G1",))),
            ("환율", _report("환율", citations=("G2",))),
        ],
        topic="오늘의 브리핑",
        reference_date=REFERENCE_DATE,
    )

    assert "- 반도체: 반도체 요약" in merged.summary
    assert "- 환율: 환율 요약" in merged.summary
    assert merged.title == "오늘의 브리핑 요약 (2026-08-11)"


def test_single_surviving_topic_is_returned_unwrapped() -> None:
    """주제가 하나만 남으면 굳이 감싸지 않고 그 보고서를 그대로 쓴다.

    나머지 주제가 근거 부족으로 빠진 경우다. 한 주제짜리 본문에 주제 헤더를
    덧씌우면 단일 주제 리포트와 형태가 달라진다.
    """
    only = _report("반도체", citations=("G1",))

    merged = merge_topic_delta_reports(
        [("반도체", only)], topic="오늘의 브리핑", reference_date=REFERENCE_DATE
    )

    assert merged is only


def test_empty_report_list_is_rejected() -> None:
    """합칠 보고서가 없으면 조용히 빈 카드를 만들지 않고 실패시킨다."""
    with pytest.raises(ValueError):
        merge_topic_delta_reports(
            [], topic="오늘의 브리핑", reference_date=REFERENCE_DATE
        )
