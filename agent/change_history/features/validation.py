"""델타 산출물의 정합성 검증 (LLM 호출 없음, 무료·결정적).

**이미 있는 검증을 다시 만들지 않는다.** 본문 길이·인용 비율은 `quality.py`가,
인용과 원문의 대조는 review 노드의 Critic이 이미 담당한다. 여기서 보는 것은
그 둘이 구조적으로 볼 수 없는 사각지대뿐이다.

Critic은 오늘 수집한 contexts만 볼 수 있고 델타 테이블(과거 팩트)은 전혀 모른다.
그래서 "before 값이 진짜 DB 기록인가"는 Critic이 확인할 방법이 없다. 이것만
여기서 결정적 코드로 검증한다.

1. **팩트 정합성** — Diff worker가 찍은 updates_fact_id가 (1) 실제 DB에 있고
   (2) 이 (user_id, topic) 소속인가. before 문구는 이 ID로 읽은 값을 그대로
   쓰므로 LLM이 과거값을 재작성할 여지 자체가 없다.
   → **한계**: "존재하지만 엉뚱한 팩트를 가리킨 의미적 오매칭"은 코드로 잡을
     수 없다. v1에서는 감수하고 진행한다.
2. **날짜 타당성** — 타임라인 절대 날짜가 기준일 대비 타당한 범위인가.
3. **인용 마커 존재** — Compose의 overview와 Impact의 implications에 유효한
   참조 마커가 하나라도 있는가. Critic은 마커를 찾아 원문과 대조하는 방식으로만
   검증하므로, 마커가 없는 섹션은 **Critic이 통과시켜도 아무것도 확인하지 않은
   것**이다. 프롬프트로 부탁만 해서는 지켜지지 않아(2026-08-05 실측:
   overview 보유율 0.692) 코드로 확인하고 해당 워커만 다시 시킨다.
4. **갱신 값의 실질 변화** — updated로 찍힌 팩트의 오늘 값이 before 값(DB 기록)과
   글자까지 동일한가. Diff 규칙(값이 같으면 duplicate)은 LLM 판단이라 가끔
   지켜지지 않는다(2026-08-11 실측: "18일 만에 열대야 쉬어가" → "18일 만에
   열대야 쉬어가"처럼 before/after가 완전히 같은 채로 "달라진 사실"에 나갔다).
   같은 문자열을 화살표로 이어 붙이면 사용자에게 "달라졌다"는 거짓 신호가
   되므로, 여기서 걸러 duplicate로 되돌린다.

검증은 **조립 이전, 워커별 출력이 아직 분리되어 있는 시점**에 수행한다. 그래야
실패했을 때 어느 워커가 문제였는지 특정해 그 워커만 다시 시킬 수 있다.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from psycopg import AsyncConnection

from infrastructure.persistence.api import (
    load_change_history_facts_by_ids,
    set_personal_wiki_scope,
)
from shared.change_history_models import UPDATED

from .compose import TimelineDraft
from .dates import (
    describe_date_problem,
    is_plausible_date,
    normalize_precision,
    parse_absolute_date,
)
from .diff import DiffFact

logger = logging.getLogger("agent.change_history.validation")

type DictRow = dict[str, Any]

# 문제를 만든 워커. Supervisor가 이 값으로 "그 워커만" 재작업시킨다.
DIFF_WORKER = "diff"
COMPOSE_WORKER = "compose"
IMPACT_WORKER = "impact"

# 본문 속 인용 표기. quality.py·critic.py·assembly.py의 정규식과 같은 형식이며,
# 함께 유지해야 한다(P=개인 Wiki, G=Global, L=실시간).
_CITATION_REF = re.compile(r"\[([PGL]\d+)\]")


def has_valid_citation(text: str, available_references: Sequence[str]) -> bool:
    """서술에 **실제로 존재하는** 근거를 가리키는 인용 마커가 하나라도 있는지 본다.

    없는 참조(예: 근거 목록에 없는 G9)는 세지 않는다 — 마커처럼 보여도 Critic이
    원문을 꺼낼 수 없어 검증에 쓸모가 없기 때문이다.
    """
    allowed = {str(reference) for reference in available_references}
    return any(ref in allowed for ref in _CITATION_REF.findall(text or ""))


@dataclass(frozen=True, slots=True)
class ValidatedFact:
    """검증을 통과한 팩트와, 코드가 채운 before 값·절대 날짜.

    Attributes:
        before_value: 갱신 대상 과거 팩트의 값. **DB에서 읽은 값**이다.
        occurred_on: 타임라인 절대 날짜. 타당한 날짜가 없으면 None.
    """

    fact: DiffFact
    before_value: str = ""
    before_statement: str = ""
    occurred_on: date | None = None
    date_precision: str = "unknown"
    timeline_description: str = ""


@dataclass(frozen=True, slots=True)
class ValidationProblem:
    """검증에서 걸러진 항목 하나와 그 사유."""

    worker: str
    reason: str
    subject: str = ""
    detail: str = ""

    def as_flag(self) -> dict[str, object]:
        """실행 기록(dropped_flags)에 남길 형태로 바꾼다."""
        return {
            "worker": self.worker,
            "reason": self.reason,
            "subject": self.subject,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    """워커별 출력 검증 결과.

    Attributes:
        facts: 통과한 팩트. 조립과 저장은 이것만 쓴다.
        problems: 걸러진 항목과 사유. 비어 있지 않으면 Supervisor가 해당 워커를
            1회 재작업시키고, 재작업 후에도 남으면 드롭 플래그로 남긴다.
    """

    facts: tuple[ValidatedFact, ...] = ()
    problems: tuple[ValidationProblem, ...] = ()

    @property
    def failed_workers(self) -> frozenset[str]:
        """문제를 만든 워커 이름 집합."""
        return frozenset(problem.worker for problem in self.problems)


async def validate_delta_outputs(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    topic: str,
    facts: Sequence[DiffFact],
    timeline: Sequence[TimelineDraft],
    reference_date: date,
    overview: str = "",
    implications: str = "",
) -> ValidationOutcome:
    """팩트 정합성·날짜 타당성·인용 마커를 검사하고 before 값을 DB에서 채운다.

    Args:
        connection: 델타 테이블 조회에 사용할 DB 연결
        user_id: 대상 사용자 식별자
        topic: 보고서 주제
        facts: Diff worker가 뽑은 신규·갱신 팩트
        timeline: Compose worker가 만든 타임라인 초안
        reference_date: 날짜 타당성 판정 기준일
        overview: Compose worker가 쓴 종합 브리핑 (인용 마커 검사 대상)
        implications: Impact worker가 쓴 파급효과 (인용 마커 검사 대상)

    Returns:
        통과한 팩트와 걸러진 항목 목록
    """
    referenced_ids = [
        fact.updates_fact_id
        for fact in facts
        if fact.verdict == UPDATED and fact.updates_fact_id
    ]
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        base_facts = await load_change_history_facts_by_ids(
            connection, user_id=user_id, topic=topic, fact_ids=referenced_ids
        )

    # 타임라인 항목을 팩트 순번으로 묶는다. 같은 팩트에 여러 항목이 오면 첫 번째만
    # 쓴다 — 한 팩트가 타임라인 여러 줄을 차지하면 같은 사실이 중복 노출된다.
    timeline_by_index: dict[int, TimelineDraft] = {}
    problems: list[ValidationProblem] = []
    for entry in timeline:
        if entry.fact_index < 0 or entry.fact_index >= len(facts):
            problems.append(
                ValidationProblem(
                    worker=COMPOSE_WORKER,
                    reason="timeline_fact_index_missing",
                    detail=f"존재하지 않는 팩트 순번을 가리켰습니다: {entry.fact_index}",
                )
            )
            continue
        timeline_by_index.setdefault(entry.fact_index, entry)

    validated: list[ValidatedFact] = []
    for index, fact in enumerate(facts):
        before_value = ""
        before_statement = ""
        if fact.verdict == UPDATED:
            base = base_facts.get(str(fact.updates_fact_id or ""))
            if base is None:
                # 존재하지 않거나 다른 사용자·주제의 팩트를 가리켰다. 이 팩트는
                # before/after를 만들 수 없으므로 통과시키지 않는다.
                problems.append(
                    ValidationProblem(
                        worker=DIFF_WORKER,
                        reason="updates_fact_id_not_found",
                        subject=f"{fact.subject} / {fact.attribute}",
                        detail=(
                            "갱신 대상으로 찍은 과거 팩트를 이 사용자·주제에서 "
                            f"찾을 수 없습니다: {fact.updates_fact_id}"
                        ),
                    )
                )
                continue
            before_value = base.fact_value
            before_statement = base.statement

            if before_value.strip() == fact.fact_value.strip():
                # LLM이 값이 같은데도 updated로 착각했다. 사용자에게 "달라졌다"는 거짓
                # 신호를 주지 않기 위해 여기서 걸러 duplicate로 되돌린다(조립에서 뺀다).
                problems.append(
                    ValidationProblem(
                        worker=DIFF_WORKER,
                        reason="updated_value_unchanged",
                        subject=f"{fact.subject} / {fact.attribute}",
                        detail=(
                            "과거 값과 오늘 값이 완전히 동일합니다. "
                            "실질적인 변화가 없으므로 duplicate로 간주해 보고서에서 제외합니다."
                        ),
                    )
                )
                continue

        entry = timeline_by_index.get(index)
        occurred_on: date | None = None
        precision = "unknown"
        description = ""
        if entry is not None:
            description = entry.description
            precision = normalize_precision(entry.precision)
            parsed = parse_absolute_date(entry.raw_date)
            if parsed is None and entry.raw_date:
                problems.append(
                    ValidationProblem(
                        worker=COMPOSE_WORKER,
                        reason="timeline_date_unparsable",
                        subject=f"{fact.subject} / {fact.attribute}",
                        detail=f"절대 날짜로 읽을 수 없는 값입니다: {entry.raw_date}",
                    )
                )
            elif parsed is not None and not is_plausible_date(
                parsed, reference_date=reference_date
            ):
                problems.append(
                    ValidationProblem(
                        worker=COMPOSE_WORKER,
                        reason="timeline_date_out_of_range",
                        subject=f"{fact.subject} / {fact.attribute}",
                        detail=describe_date_problem(
                            parsed, reference_date=reference_date
                        ),
                    )
                )
            else:
                occurred_on = parsed
            if occurred_on is None:
                # 날짜를 못 믿을 뿐이지 팩트 자체는 살아 있다. 타임라인 줄만 뺀다.
                precision = "unknown"
                description = ""

        validated.append(
            ValidatedFact(
                fact=fact,
                before_value=before_value,
                before_statement=before_statement,
                occurred_on=occurred_on,
                date_precision=precision,
                timeline_description=description,
            )
        )

    # 인용 마커 검사. 인용할 수 있는 근거가 애초에 없으면(모든 팩트의
    # source_reference가 비었으면) 다시 시켜도 마커가 생기지 않으므로 건너뛴다.
    available = [fact.source_reference for fact in facts if fact.source_reference]
    if available:
        if overview.strip() and not has_valid_citation(overview, available):
            problems.append(
                ValidationProblem(
                    worker=COMPOSE_WORKER,
                    reason="overview_missing_citation",
                    detail=(
                        "종합 브리핑에 유효한 인용 마커가 없어 Critic이 원문과 "
                        "대조할 대상이 없습니다."
                    ),
                )
            )
        if implications.strip() and not has_valid_citation(implications, available):
            problems.append(
                ValidationProblem(
                    worker=IMPACT_WORKER,
                    reason="implications_missing_citation",
                    detail=(
                        "파급효과 서술에 유효한 인용 마커가 없어 Critic이 원문과 "
                        "대조할 대상이 없습니다."
                    ),
                )
            )

    if problems:
        logger.info(
            "델타 검증에서 %d건을 걸렀습니다 (문제 워커: %s)",
            len(problems),
            ", ".join(sorted({problem.worker for problem in problems})),
        )
    return ValidationOutcome(facts=tuple(validated), problems=tuple(problems))


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def chg_005(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    topic: str,
    facts: Sequence[DiffFact],
    timeline: Sequence[TimelineDraft],
    reference_date: date,
    overview: str = "",
    implications: str = "",
) -> ValidationOutcome:
    """[CHG-005] 델타 정합성 검증.

    Diff worker가 찍은 갱신 대상 ID가 이 사용자·주제의 실제 기록인지, 타임라인
    절대 날짜가 기준일 대비 타당한지, 워커가 쓴 서술에 유효한 인용 마커가
    있는지를 코드로 검사한다(LLM 호출 없음).
    """
    return await validate_delta_outputs(
        connection,
        user_id=user_id,
        topic=topic,
        facts=facts,
        timeline=timeline,
        reference_date=reference_date,
        overview=overview,
        implications=implications,
    )
