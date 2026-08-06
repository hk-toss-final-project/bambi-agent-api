"""타임라인 날짜의 정형화 규칙과 타당성 검사 (LLM 호출 없음, 무료·결정적).

Compose worker에게 "모호한 날짜 표현을 절대 날짜(YYYY-MM-DD)로 바꿔라"라고만
시키면 모델마다 다른 규칙을 쓴다("2026년 하반기"를 07-01로 쓰기도 하고 12-31로
쓰기도 한다). 그래서 **규칙을 여기 한 곳에 적고 프롬프트에 그대로 주입한 뒤,
돌아온 값을 같은 규칙으로 다시 검사**한다.

기준일(reference_date)은 하드코딩하지 않고 실행 시 주입받는다 — 테스트가
"오늘"에 따라 결과가 바뀌지 않게 하기 위함이다.
"""

from __future__ import annotations

from datetime import date

# ── 확정 불가 표기의 정형화 규칙 ────────────────────────────────────────────
# 구간으로만 알 수 있는 표현은 **해당 구간의 첫날**로 통일하고, 원래 정밀도를
# date_precision에 남긴다. 첫날로 정하는 이유는 "그 시점 이후"라는 뜻이 보존되고,
# 정렬했을 때 구간이 실제 사건보다 앞서 놓이기 때문이다.
#
#   상반기            → 해당 연도 01-01 (precision=half)
#   하반기            → 해당 연도 07-01 (precision=half)
#   1·2·3·4분기       → 01-01 / 04-01 / 07-01 / 10-01 (precision=quarter)
#   YYYY년 M월        → 해당 월 01일 (precision=month)
#   연도만            → 01-01 (precision=year)
#   "곧", "조만간"    → 날짜 없음 (precision=unknown). 억지로 찍지 않는다.
DATE_RULES_PROMPT = (
    "날짜 표기 규칙:\n"
    "- 모든 날짜는 YYYY-MM-DD 형식의 절대 날짜로 적는다.\n"
    "- '오늘·어제·이번 주' 같은 상대 표현은 주어진 기준일로 환산한다.\n"
    "- 구간으로만 알 수 있으면 그 구간의 첫날로 적고 precision을 함께 남긴다.\n"
    "  상반기→01-01(half), 하반기→07-01(half), 1/2/3/4분기→01-01/04-01/07-01/10-01(quarter),\n"
    "  'YYYY년 M월'→그 달 01일(month), 연도만→01-01(year), 정확한 날짜→그대로(day).\n"
    "- '곧'·'조만간'처럼 시점을 알 수 없으면 date를 비우고 precision을 unknown으로 둔다.\n"
    "- 자료에 없는 날짜를 추측해서 만들지 않는다.\n"
)

# ── 타당성 범위 ────────────────────────────────────────────────────────────
# 기준일에서 이만큼 벗어난 날짜는 환각이나 파싱 오류로 본다. 과거를 넓게 잡는
# 이유는 연혁·전사(前史)를 타임라인에 넣는 경우가 있어서고, 미래를 좁게 잡는
# 이유는 "2030년 양산" 같은 먼 계획이 오늘의 변화로 오인되지 않게 하기 위함이다.
PAST_LIMIT_DAYS = 365 * 5
FUTURE_LIMIT_DAYS = 365 * 3

VALID_PRECISIONS = ("day", "month", "quarter", "half", "year", "unknown")


def parse_absolute_date(value: str | None) -> date | None:
    """YYYY-MM-DD 문자열을 date로 바꾼다. 형식이 어긋나면 None."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def normalize_precision(value: str | None) -> str:
    """정밀도 값을 허용 목록으로 정리한다. 모르는 값은 unknown."""
    text = str(value or "").strip().lower()
    return text if text in VALID_PRECISIONS else "unknown"


def is_plausible_date(value: date, *, reference_date: date) -> bool:
    """타임라인 날짜가 기준일 대비 타당한 범위 안인지 판정한다.

    Args:
        value: 검사할 절대 날짜
        reference_date: 실행 시 주입된 기준일

    Returns:
        과거 5년 ~ 미래 3년 범위 안이면 True
    """
    delta = (value - reference_date).days
    return -PAST_LIMIT_DAYS <= delta <= FUTURE_LIMIT_DAYS


def describe_date_problem(value: date, *, reference_date: date) -> str:
    """타당하지 않은 날짜의 사유를 사람이 읽는 문장으로 만든다."""
    delta = (value - reference_date).days
    if delta < -PAST_LIMIT_DAYS:
        return f"기준일({reference_date})보다 {abs(delta)}일 과거라 타임라인 범위를 벗어납니다."
    return f"기준일({reference_date})보다 {delta}일 미래라 타임라인 범위를 벗어납니다."
