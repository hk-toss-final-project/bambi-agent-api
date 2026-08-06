"""변경점(Delta) 추적 경계에서 공유하는 순수 데이터 구조.

영속화(infrastructure)가 만들고 에이전트(agent)가 소비하는 과거 팩트와,
에이전트가 만들고 영속화가 저장하는 신규 팩트를 정의해 두 계층이 서로를
import하지 않게 한다(shared/report_models.py와 같은 이유).

**팩트 하나의 정의**: (subject, attribute, fact_value) 세 요소.
중복·갱신 판정은 (subject, attribute) 매칭으로 하고, fact_value가 다르면
갱신으로 본다. 예) subject="B사 HBM4", attribute="양산 일정",
fact_value="2026-3Q로 연기".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# 팩트 판정 결과. duplicate는 저장하지 않으므로 DB verdict에는 들어가지 않는다.
NEW = "new"
UPDATED = "updated"
DUPLICATE = "duplicate"

# 타임라인 날짜 정밀도. 확정 불가한 표기(반기·분기 등)는 해당 구간 첫날로
# 정규화하고 원래 정밀도를 여기에 남긴다.
DATE_PRECISIONS = frozenset({"day", "month", "quarter", "half", "year", "unknown"})


@dataclass(frozen=True, slots=True)
class ChangeHistoryFact:
    """델타 테이블에 저장된 과거 팩트 한 건.

    Diff worker의 도구(search_base_facts)와 검증(팩트 정합성)이 함께 읽는다.
    """

    fact_id: str
    subject: str
    attribute: str
    fact_value: str
    statement: str
    verdict: str
    occurred_on: date | None = None
    date_precision: str = "unknown"
    source_reference: str | None = None
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class NewChangeHistoryFact:
    """이번 실행에서 추출해 저장할 팩트 한 건.

    Attributes:
        supersedes_fact_id: 갱신 대상 과거 팩트 ID. 검증을 통과한 값만 담긴다
            (LLM이 찍은 값을 그대로 저장하지 않는다).
        before_value: 갱신 대상 팩트의 과거 값. **DB에서 읽어 채운다** —
            LLM이 과거값을 다시 쓸 여지를 없애기 위함이다.
    """

    subject: str
    attribute: str
    fact_value: str
    statement: str
    verdict: str
    supersedes_fact_id: str | None = None
    before_value: str = ""
    occurred_on: date | None = None
    date_precision: str = "unknown"
    source_reference: str | None = None
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class ChangeHistoryRunRecord:
    """저장된 변경점 추적 실행 한 건.

    "직전 보고서"를 날짜가 아니라 이 실행 기록으로 잡는다 — 매일 돌지 않아도
    델타가 끊기지 않게 하기 위함이다.
    """

    run_id: str
    user_id: str
    topic: str
    reference_date: date
    is_first_run: bool
    outcome: str
    new_fact_count: int = 0
    updated_fact_count: int = 0
    duplicate_fact_count: int = 0


@dataclass(frozen=True, slots=True)
class LatestReportSnapshot:
    """(user_id, topic)의 가장 최근 발행 Snapshot 본문.

    Overview가 과거 맥락으로 삼는 (a)맥락 요약이다. Markdown 본문뿐이라 팩트
    대조에는 쓸 수 없고, 그쪽은 델타 테이블(b)이 담당한다.
    """

    title: str
    summary: str
    body: str
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class PersistedChangeHistoryRun:
    """델타 실행과 팩트를 저장한 결과."""

    run_id: str
    fact_ids: tuple[str, ...] = ()
    superseded_fact_ids: tuple[str, ...] = field(default=())
