"""검증을 통과한 워커 출력을 하나의 markdown 보고서로 조립한다 (LLM 아님, 코드).

**이 단계에 LLM을 쓰지 않는다.** 최종 보고서를 LLM으로 다시 쓰게 하면 정형
포맷과 before/after 수치가 재작성 과정에서 훼손된다. 섹션 헤더를 붙여 이어
붙이는 일은 문자열 조작이지 생성이 아니다.

이 보고서는 "달라진 것만" 보여주는 별도 문서가 아니라, 평소 받는 정보요약
보고서 그대로 + 달라진 점 하이라이트다. 그래서 title·summary는 이번 보고서
전체의 제목과 한 줄 결론이고, 본문은 네 섹션 순서로 구성된다.

    1. 이번에 달라진 점  — 신규·갱신 팩트만, before → after 비교
    2. 핵심 요약·맥락    — Compose가 신규·갱신·유지 전체로 쓴 종합 요약
    3. 주목할 점         — 앞으로 확인할 지표·리스크(행동 지시 아님)
    4. 타임라인          — 확정 가능한 날짜가 있을 때만 노출

장식 기호(이모지)는 쓰지 않는다.

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

UPDATES_HEADING = "## 이번에 달라진 점"
OVERVIEW_HEADING = "## 보고서 내용"
IMPLICATIONS_HEADING = "## 주목할 점"
TIMELINE_HEADING = "## 타임라인"

# "이번에 달라진 점" 안을 성격별로 나누는 소제목. 갱신과 신규를 한 목록에 섞으면
# "무엇이 달라졌나"가 눈에 들어오지 않는다 — 이 기능의 존재 이유가 그것이므로
# 섹션부터 갈라 놓는다. 소비하는 쪽(웹 화면·풀스택)도 이 소제목으로 구분한다.
CHANGED_SUBHEADING = "### 달라진 사실"
NEW_SUBHEADING = "### 새로 확인된 사실"

FIRST_RUN_NOTICE = "이 주제의 최초 실행이라 비교 대상이 없습니다. 오늘 확인된 내용을 전부 정리했습니다."
NO_CHANGE_NOTICE = "직전 보고서 이후 새로 확인되거나 달라진 내용이 없습니다."
NO_WATCH_ITEMS_NOTICE = "이번에 특별히 주목할 사항은 없습니다."


def _changed_line(item: ValidatedFact) -> str:
    """달라진 사실을 (기존)과 (변경) 텍스트로 위아래 렌더링한다."""
    fact = item.fact
    marker = f" [{fact.source_reference}]" if fact.source_reference else ""
    before = item.before_value or "(이전 값 없음)"
    return (
        f"  (기존) ~~{before}~~\n"
        f"  (변경) `{fact.today_statement}`{marker}"
    )


def _new_line(item: ValidatedFact) -> str:
    """새로 확인된 사실을 배경색 없는 일반 텍스트로 만든다."""
    fact = item.fact
    marker = f" [{fact.source_reference}]" if fact.source_reference else ""
    return f"- {fact.today_statement}{marker}"


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


def _deduplicate_facts(facts: Sequence[ValidatedFact]) -> list[ValidatedFact]:
    """동일 서술문이 중복되거나 유사 팩트가 겹칠 경우 첫 팩트만 남기고 정제한다."""
    seen_statements: set[str] = set()
    result: list[ValidatedFact] = []
    for item in facts:
        stmt = item.fact.today_statement.strip()
        if stmt not in seen_statements:
            seen_statements.add(stmt)
            result.append(item)
    return result


def build_delta_markdown(
    *,
    highlight_facts: Sequence[ValidatedFact],
    compose: ComposeOutcome,
    impact: ImpactOutcome,
    is_first_run: bool = False,
) -> str:
    """섹션 헤더를 붙여 네 섹션을 하나의 markdown 문자열로 잇는다.

    이 보고서는 "달라진 것만" 보여주는 문서가 아니라 평소와 같은 정보요약
    보고서다. "핵심 요약·맥락"은 Compose가 신규·갱신·유지 팩트 전체로 쓴
    종합 요약을 그대로 쓰고(항상 채워진다), "이번에 달라진 점"에만
    highlight_facts(신규·갱신)를 따로 추려 보여준다.

    제목·한 줄 결론은 여기 안 넣는다 — `GeneratedReportContent.title`·
    `.summary` 필드가 이미 그 값을 나른다. 본문에 다시 박으면 카드 헤더와
    본문 양쪽에 같은 제목이 중복 노출되는 소비 측 문제가 생긴다.

    Args:
        highlight_facts: 이번에 달라진 팩트(신규·갱신)만. 유지(중복)는 이미
            제외된 상태로 들어온다 — 비어 있으면 "달라진 점이 없다"는 뜻이다.
        compose: 핵심 요약·타임라인 생성 결과
        impact: 파급효과·확인 사항 추론 결과 (달라진 점이 없으면 실행되지
            않아 비어 있을 수 있다)
        is_first_run: 비교 대상이 없던 최초 실행인지

    Returns:
        이번에 달라진 점·핵심 요약·주목할 점·타임라인을 담은 markdown 본문
        (타임라인은 확정 가능한 날짜가 있을 때만 포함된다)
    """
    no_change = not highlight_facts

    blocks: list[str] = [UPDATES_HEADING]
    if is_first_run:
        blocks.append(FIRST_RUN_NOTICE)
    if no_change:
        blocks.append(NO_CHANGE_NOTICE)
    else:
        changed = _deduplicate_facts([item for item in highlight_facts if item.fact.verdict == UPDATED])
        fresh = _deduplicate_facts([item for item in highlight_facts if item.fact.verdict != UPDATED])[:5]
        # 달라진 것을 먼저 보여준다 — 이 보고서를 여는 이유가 그것이다.
        if changed:
            blocks.append(f"{CHANGED_SUBHEADING} ({len(changed)}건)")
            blocks.append("\n\n".join(_changed_line(item) for item in changed))
        if fresh:
            blocks.append(f"{NEW_SUBHEADING} ({len(fresh)}건)")
            blocks.append("\n\n".join(_new_line(item) for item in fresh))

    blocks.append(OVERVIEW_HEADING)
    blocks.append(compose.overview.strip() or "정리할 내용이 없습니다.")

    blocks.append(IMPLICATIONS_HEADING)
    if impact.implications.strip():
        blocks.append(impact.implications.strip())
        if impact.actions:
            blocks.append("**확인이 필요한 부분**")
            blocks.append("\n".join(f"- {action}" for action in impact.actions))
    else:
        blocks.append(NO_WATCH_ITEMS_NOTICE)

    # 타임라인은 확정 가능한 날짜가 있을 때만 섹션 자체를 넣는다. 없는데도
    # 자리만 차지하면 "빈 섹션을 보여주는" 문서가 된다.
    timeline = _timeline_lines(highlight_facts)
    if timeline:
        blocks.append(TIMELINE_HEADING)
        blocks.extend(timeline)

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
    highlight_facts: Sequence[ValidatedFact],
    compose: ComposeOutcome,
    impact: ImpactOutcome,
    contexts: Sequence[ReportContextDocument],
    is_first_run: bool = False,
) -> GeneratedReportContent:
    """조립한 markdown을 기존 생성 결과와 같은 형태로 감싸 돌려준다.

    title·summary는 compose가 만든 "제목 + 한 줄 결론"을 그대로 쓴다 — 이
    보고서는 평소 요약 보고서와 같은 자리에 나가므로, 카드 제목·미리보기가
    "달라진 점 몇 건"이 아니라 실제 결론을 담아야 한다.

    Args:
        topic: 보고서 주제
        reference_date: 기본 제목에 쓸 기준일 (compose가 제목을 못 만들었을 때만 쓴다)
        highlight_facts: 이번에 달라진 팩트(신규·갱신)만
        compose: 핵심 요약·타임라인 생성 결과 (제목·한 줄 결론도 여기서 온다)
        impact: 파급효과·확인 사항 추론 결과
        contexts: 오늘 수집한 근거 문서 (Citation 참조 검증용)
        is_first_run: 비교 대상이 없던 최초 실행인지

    Returns:
        review(Critic)와 persist가 그대로 소비할 수 있는 생성 콘텐츠
    """
    title = compose.title.strip() or f"{topic} 요약 ({reference_date.isoformat()})"
    summary = compose.summary.strip()
    if not summary:
        summary = (
            f"{reference_date.isoformat()} 기준 {topic}의 달라진 점 "
            f"{len(highlight_facts)}건을 정리했습니다."
        )
    body = build_delta_markdown(
        highlight_facts=highlight_facts,
        compose=compose,
        impact=impact,
        is_first_run=is_first_run,
    )
    return GeneratedReportContent(
        title=title,
        summary=summary,
        body=body,
        citation_references=collect_allowed_citations(body, contexts),
    )


# markdown 제목 줄. 주제별 보고서를 한 장으로 합칠 때 단계를 한 칸씩 내린다.
_HEADING_LINE = re.compile(r"^(#{1,5})(?=\s)", re.MULTILINE)


def _demote_headings(body: str) -> str:
    """본문의 markdown 제목 단계를 한 칸씩 내린다.

    주제별 보고서는 저마다 `##` 섹션 헤딩으로 시작한다. 그대로 이어 붙이면 주제
    구분과 섹션 구분이 같은 단계가 돼 어디부터 다른 주제인지 읽을 수 없다.
    """
    return _HEADING_LINE.sub(lambda match: "#" + match.group(1), body)


def merge_topic_delta_reports(
    reports: Sequence[tuple[str, GeneratedReportContent]],
    *,
    topic: str,
    reference_date: date,
) -> GeneratedReportContent:
    """주제별 델타 보고서를 한 장의 카드 본문으로 합친다 (LLM 아님, 코드).

    아침 브리핑처럼 주제가 여럿인 요청은 주제마다 델타를 따로 돌린다. 비교축이
    (user_id, topic)이라 한 축으로 묶으면 주제별 변화가 구분되지 않기 때문이다.
    합치는 일은 문자열 조작이라 여기서도 LLM을 쓰지 않는다(chg_006과 같은 이유).

    **주제가 하나만 살아남아도 항상 감싸고 헤딩을 한 칸 내린다.** 이 함수를
    부르는 시점 자체가 "다주제 델타 요청이었다"는 뜻이라, 근거 부족으로 다른
    주제가 빠져 결과가 1건이 됐다고 안 감싸면, 같은 다주제 요청인데도 살아남은
    주제 수(생성 이후에야 정해지는 값)에 따라 `##`/`###` 헤딩 단계가 갈린다.
    프론트가 body 구조를 요청 시점에 예측할 수 없게 되므로(2026-08-11 풀스택
    피드백), 헤딩 단계는 오직 "다주제 요청이었는가"로만 정해지게 고정한다.

    Args:
        reports: (주제, 그 주제의 델타 보고서) 목록. 순서를 그대로 유지한다.
            1건이어도(다른 주제가 근거 부족으로 빠졌어도) 감싼다
        topic: 카드 제목에 쓸 요청 대표 주제
        reference_date: 기본 제목에 쓸 기준일

    Returns:
        주제별 섹션을 이어 붙인 하나의 생성 콘텐츠. 항상 `## {주제}` 아래
        `### `로 한 칸 내려간 섹션 헤딩을 담는다

    Raises:
        ValueError: 합칠 보고서가 한 건도 없는 경우
    """
    if not reports:
        raise ValueError("합칠 주제별 델타 보고서가 없습니다.")

    blocks: list[str] = []
    summaries: list[str] = []
    citations: list[str] = []
    tags: list[str] = []
    for section_topic, report in reports:
        blocks.append(f"## {section_topic}")
        blocks.append(_demote_headings(report.body).strip())
        if report.summary.strip():
            summaries.append(f"- {section_topic}: {report.summary.strip()}")
        for reference in report.citation_references:
            if reference not in citations:
                citations.append(reference)
        for tag in report.content_tags:
            if tag not in tags:
                tags.append(tag)
    summary = "\n".join(summaries) or (
        f"{reference_date.isoformat()} 기준 주제 {len(reports)}건의 변화를 정리했습니다."
    )
    return GeneratedReportContent(
        title=f"{topic} 요약 ({reference_date.isoformat()})",
        summary=summary,
        body="\n\n".join(block for block in blocks if block),
        citation_references=tuple(citations),
        content_tags=tuple(tags),
    )


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def chg_006(
    *,
    topic: str,
    reference_date: date,
    highlight_facts: Sequence[ValidatedFact],
    compose: ComposeOutcome,
    impact: ImpactOutcome,
    contexts: Sequence[ReportContextDocument],
    is_first_run: bool = False,
) -> GeneratedReportContent:
    """[CHG-006] 정보요약보고서 조립.

    Compose·Impact 출력에 섹션 헤더를 붙여 하나의 markdown으로 잇는다. 이
    단계에는 LLM을 쓰지 않는다 — 재작성 과정에서 before/after 수치와 정형
    포맷이 훼손되기 때문이다.
    """
    return assemble_delta_report(
        topic=topic,
        reference_date=reference_date,
        highlight_facts=highlight_facts,
        compose=compose,
        impact=impact,
        contexts=contexts,
        is_first_run=is_first_run,
    )
