"""검증을 통과한 워커 출력을 하나의 markdown 보고서로 조립한다 (LLM 아님, 코드).

**이 단계에 LLM을 쓰지 않는다.** 최종 보고서를 LLM으로 다시 쓰게 하면 정형
포맷과 before/after 수치가 재작성 과정에서 훼손된다. 섹션 헤더를 붙여 이어
붙이는 일은 문자열 조작이지 생성이 아니다.

조립 결과는 기존 review 노드가 읽는 것과 **같은 형태**(GeneratedReportContent)로
돌려준다. 그래야 Critic 검증과 기존 persist_report_generation 저장이 그대로
이어지고, PublishSnapshotResponse.body(단일 markdown)까지 계약이 바뀌지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from shared.change_history_models import UPDATED
from shared.report_models import GeneratedReportContent, ReportContextDocument

from .compose import ComposeOutcome
from .impact import ImpactOutcome
from .validation import ValidatedFact

# 본문 속 인용 표기. quality.py·critic.py의 _CITATION_REF와 같은 형식이며,
# 셋을 함께 유지해야 한다(P=개인 Wiki, G=Global, L=실시간).
_CITATION_REF = re.compile(r"\[([PGL]\d+)\]")

OVERVIEW_HEADING = "## Overview"
UPDATES_HEADING = "## 🔥 주요 업데이트"
TIMELINE_HEADING = "## 📅 타임라인"
IMPLICATIONS_HEADING = "## 💡 시사점"

# 주요 업데이트 안을 성격별로 나누는 소제목. 갱신과 신규를 한 목록에 섞으면
# "무엇이 달라졌나"가 눈에 들어오지 않는다 — 이 기능의 존재 이유가 그것이므로
# 섹션부터 갈라 놓는다. 소비하는 쪽(웹 화면·풀스택)도 이 소제목으로 구분한다.
CHANGED_SUBHEADING = "### 🔁 달라진 사실"
NEW_SUBHEADING = "### 🆕 새로 확인된 사실"

FIRST_RUN_NOTICE = "> 이 주제의 최초 실행이라 비교 대상이 없습니다. 오늘 확인된 내용을 전부 신규로 정리했습니다."
NO_CHANGE_NOTICE = "> 직전 보고서 이후 새로 확인된 변화가 없습니다."


def _changed_line(item: ValidatedFact) -> str:
    """달라진 사실 한 줄을 `이전 → 오늘` 형태로 만든다.

    before는 코드가 DB에서 읽은 과거값이라 LLM이 손댈 수 없다. 두 값을 백틱으로
    나란히 붙여, 읽는 쪽이 무엇이 무엇으로 바뀌었는지 한눈에 보게 한다.
    """
    fact = item.fact
    marker = f" [{fact.source_reference}]" if fact.source_reference else ""
    before = item.before_value or "(이전 값 없음)"
    after = fact.fact_value or "(값 없음)"
    return (
        f"- **{fact.subject} · {fact.attribute}** — `{before}` → `{after}`{marker}\n"
        f"  - {fact.today_statement}"
    )


def _new_line(item: ValidatedFact) -> str:
    """새로 확인된 사실 한 줄을 만든다(비교 대상이 없으므로 값 하나만 적는다)."""
    fact = item.fact
    marker = f" [{fact.source_reference}]" if fact.source_reference else ""
    value = fact.fact_value or "(값 없음)"
    return (
        f"- **{fact.subject} · {fact.attribute}** — `{value}`{marker}\n"
        f"  - {fact.today_statement}"
    )


def _timeline_lines(facts: Sequence[ValidatedFact]) -> list[str]:
    """타임라인 항목을 날짜 오름차순으로 정렬해 만든다."""
    dated = [item for item in facts if item.occurred_on and item.timeline_description]
    dated.sort(key=lambda item: item.occurred_on or date.min)
    lines: list[str] = []
    for item in dated:
        assert item.occurred_on is not None  # dated 필터가 보장한다.
        suffix = "" if item.date_precision == "day" else f" ({item.date_precision})"
        lines.append(
            f"- **{item.occurred_on.isoformat()}**{suffix} — {item.timeline_description}"
        )
    return lines


def build_delta_markdown(
    *,
    facts: Sequence[ValidatedFact],
    compose: ComposeOutcome,
    impact: ImpactOutcome,
    is_first_run: bool = False,
    no_change: bool = False,
) -> str:
    """섹션 헤더를 붙여 네 섹션을 하나의 markdown 문자열로 잇는다.

    Args:
        facts: 검증을 통과한 팩트
        compose: Overview·타임라인 생성 결과
        impact: 파급효과 추론 결과
        is_first_run: 비교 대상이 없던 최초 실행인지
        no_change: 유의미한 변화가 없어 짧은 보고서로 가는지

    Returns:
        Overview·주요 업데이트·타임라인·시사점을 담은 markdown 본문
    """
    blocks: list[str] = [OVERVIEW_HEADING]
    if is_first_run:
        blocks.append(FIRST_RUN_NOTICE)
    if no_change:
        blocks.append(NO_CHANGE_NOTICE)
    blocks.append(compose.overview.strip() or "정리할 변화가 없습니다.")

    blocks.append(UPDATES_HEADING)
    changed = [item for item in facts if item.fact.verdict == UPDATED]
    fresh = [item for item in facts if item.fact.verdict != UPDATED]
    if not facts:
        blocks.append("- 새로 확인된 사실이 없습니다.")
    else:
        # 달라진 것을 먼저 보여준다 — 이 보고서를 여는 이유가 그것이다.
        if changed:
            blocks.append(f"{CHANGED_SUBHEADING} ({len(changed)}건)")
            blocks.extend(_changed_line(item) for item in changed)
        if fresh:
            blocks.append(f"{NEW_SUBHEADING} ({len(fresh)}건)")
            blocks.extend(_new_line(item) for item in fresh)

    timeline = _timeline_lines(facts)
    blocks.append(TIMELINE_HEADING)
    blocks.extend(timeline or ["- 시점을 확정할 수 있는 항목이 없습니다."])

    blocks.append(IMPLICATIONS_HEADING)
    if impact.implications.strip():
        blocks.append(impact.implications.strip())
    else:
        blocks.append("- 이번 변화만으로는 파급효과를 판단하기 어렵습니다.")
    if impact.actions:
        blocks.append("**행동 지침**")
        blocks.extend(f"- {action}" for action in impact.actions)

    return "\n\n".join(block for block in blocks if block)


def collect_allowed_citations(
    body: str, contexts: Sequence[ReportContextDocument]
) -> tuple[str, ...]:
    """본문이 실제로 인용한 참조 중 근거 목록에 있는 것만 순서대로 모은다.

    저장(persist_report_generation)은 citation_references의 참조를 근거 문서에서
    찾아 Citation Row를 만든다. 목록에 없는 참조가 섞이면 저장이 KeyError로
    깨지므로, 여기서 반드시 교집합만 남긴다.
    """
    allowed = {str(context.reference) for context in contexts}
    collected: list[str] = []
    for reference in _CITATION_REF.findall(body):
        if reference in allowed and reference not in collected:
            collected.append(reference)
    return tuple(collected)


def assemble_delta_report(
    *,
    topic: str,
    reference_date: date,
    facts: Sequence[ValidatedFact],
    compose: ComposeOutcome,
    impact: ImpactOutcome,
    contexts: Sequence[ReportContextDocument],
    is_first_run: bool = False,
    no_change: bool = False,
) -> GeneratedReportContent:
    """조립한 markdown을 기존 생성 결과와 같은 형태로 감싸 돌려준다.

    Args:
        topic: 보고서 주제
        reference_date: 기본 제목에 쓸 기준일
        facts: 검증을 통과한 팩트
        compose: Overview·타임라인 생성 결과 (제목·요약도 여기서 온다)
        impact: 파급효과 추론 결과
        contexts: 오늘 수집한 근거 문서 (Citation 참조 검증용)
        is_first_run: 비교 대상이 없던 최초 실행인지
        no_change: 유의미한 변화가 없어 짧은 보고서로 가는지

    Returns:
        review(Critic)와 persist가 그대로 소비할 수 있는 생성 콘텐츠
    """
    body = build_delta_markdown(
        facts=facts,
        compose=compose,
        impact=impact,
        is_first_run=is_first_run,
        no_change=no_change,
    )
    title = compose.title.strip() or f"{topic} 변경점 브리핑 ({reference_date.isoformat()})"
    summary = compose.summary.strip()
    if not summary:
        summary = (
            f"{reference_date.isoformat()} 기준 {topic}의 신규·갱신 사실 "
            f"{len(facts)}건을 정리했습니다."
        )
    return GeneratedReportContent(
        title=title,
        summary=summary,
        body=body,
        citation_references=collect_allowed_citations(body, contexts),
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def chg_006(
    *,
    topic: str,
    reference_date: date,
    facts: Sequence[ValidatedFact],
    compose: ComposeOutcome,
    impact: ImpactOutcome,
    contexts: Sequence[ReportContextDocument],
    is_first_run: bool = False,
    no_change: bool = False,
) -> GeneratedReportContent:
    """[CHG-006] 델타 보고서 조립.

    검증을 통과한 워커 출력에 섹션 헤더를 붙여 하나의 markdown으로 잇는다.
    이 단계에는 LLM을 쓰지 않는다 — 재작성 과정에서 before/after 수치와 정형
    포맷이 훼손되기 때문이다.
    """
    return assemble_delta_report(
        topic=topic,
        reference_date=reference_date,
        facts=facts,
        compose=compose,
        impact=impact,
        contexts=contexts,
        is_first_run=is_first_run,
        no_change=no_change,
    )
