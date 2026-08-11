"""갱신(updated) 판정의 실질 변화 여부를 코드로 재확인한다 (LLM 호출 없음, 무료·결정적).

Diff worker는 "표현만 다르고 값이 같으면 duplicate"라는 규칙을 프롬프트로 받지만
(diff.py의 판정 규칙 3), 실측에서 이 규칙이 반복적으로 무너졌다.

2026-08-11 운영 DB 실측 — `로또 / 미수령 당첨금 자동 지급 시스템` 팩트는 값이
한 번도 바뀌지 않은 채 4회 연속 updated로 기록됐다.

    04:03 new      18일부터 시행된다.
    04:18 updated  오는 18일부터 시행된다.            ← "오는 " 3글자 차이
    06:07 updated  18일부터 시행된다.                 ← 04:03과 완전히 같은 문자열
    11:11 updated  오는 18일부터 판매점에서 …있게 된다.
    11:33 updated  오는 18일부터 판매점에서 …시스템이 시행된다.

기존 안전장치는 before/after가 **글자까지 완전히 같을 때만** 걸러서 조사 하나만
붙어도 통과했다. 이 모듈이 그 자리를 대신한다.

**판정 기준은 하드 토큰(숫자·수치)이다.** 이 도메인에서 "달라졌다"의 실체는 거의
항상 날짜·수치·비율·금액이다. 산문이 어떻게 흔들렸든 하드 토큰이 그대로면 같은
사실을 다시 쓴 것으로 본다.

**임베딩 유사도를 쓰지 않는 이유**: 판별 신호가 숫자 한 글자라 임베딩이 압축해
버린다. "18일부터 시행" vs "20일부터 시행"(진짜 변경)이 "18일부터 시행" vs
"오는 18일부터 판매점에서…"(패러프레이즈)보다 오히려 더 유사하게 나와, 임계값을
어디에 잡아도 두 경우를 가를 수 없다.

**대조는 단위별로 한다.** 과거 값에 있던 단위(일·%·억…)의 숫자가 오늘 값에서도
그대로여야 패러프레이즈다. 오늘 값에만 새로 등장한 단위는 재보도가 덧붙인 세부
정보로 보고 무시한다.

    과거: 18일부터 시행된다.
    오늘: 오는 18일부터 … 4등과 5등 소액 당첨금이 자동으로 입금된다.
          → 일:{18} 그대로, 등:{4,5}는 새 단위 → 재서술

이걸 단순 집합 비교로 하면 위 예가 빠져나간다(2026-08-11 벤치 `dup_expanded`).
반대로 단위를 무시하고 부분집합만 보면 아래가 잘못 걸린다 — 그래서 단위별로 본다.

    과거: 18일부터 시행된다.
    오늘: 18일 발표, 시행은 25일부터.
          → 일:{18} vs {18,25} 불일치 → 진짜 변경

**한계**: 과거에 없던 단위가 실제 변경을 나른 경우는 놓친다("18일 접수 시작,
적용은 2분기"). 상태가 뒤집히는 흔한 형태는 극성 검사가 잡지만, 그 밖의 경우는
남는다. 이 자리는 의미 판정이 필요한 영역이라 코드로 더 밀어붙이지 않는다.

**억제는 보수적으로 한다.** 판단할 수 없으면(숫자가 없거나 상태 어휘가 상충하면)
억제하지 않고 LLM 판정을 그대로 둔다 — 진짜 변경을 지우는 쪽이 패러프레이즈를
한 줄 남기는 쪽보다 손해가 크기 때문이다.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

# 숫자에 붙는 단위. 조사("18일**부터**")까지 삼키지 않도록 **한 글자짜리 단위만**
# 허용 목록으로 고정한다. 목록을 넓히면 "18일부터"와 "18일에"가 다른 토큰이 되어
# 같은 값이 변경으로 잘못 잡힌다.
_UNIT_CHARS = "%일월년주시분초회차위등명개건배도원달억조만천"

_NUMBER_TOKEN = re.compile(rf"(\d[\d,]*(?:\.\d+)?)\s*([{_UNIT_CHARS}]?)")

# 상태가 서로 **반대로 뒤집힌** 경우만 진짜 변화로 본다. 한쪽에만 있는 단어는
# 문장을 다시 쓰면서 붙는 일이 잦아(실측: "…있게 된다" → "…시스템이 시행된다"),
# 단어 존재 여부로 판정하면 패러프레이즈를 놓친다.
_POLARITY_GROUPS = (
    (
        frozenset({"시행", "도입", "개시", "확정", "통과", "승인", "재개"}),
        frozenset({"연기", "취소", "철회", "중단", "무산", "보류", "반려", "거부", "부결"}),
    ),
    (
        frozenset({"상승", "급등", "인상", "증가", "확대", "흑자"}),
        frozenset({"하락", "급락", "인하", "감소", "축소", "적자"}),
    ),
)


def _iter_number_tokens(text: str) -> Iterator[tuple[str, str]]:
    """문장에서 (정규화된 숫자, 단위) 쌍을 순서대로 뽑는다.

    쉼표(1,000 → 1000)와 앞자리 0(08 → 8)을 없애 표기 차이를 흡수한다.
    """
    for raw_number, unit in _NUMBER_TOKEN.findall(text or ""):
        number = raw_number.replace(",", "")
        if "." in number:
            number = number.rstrip("0").rstrip(".")
        number = number.lstrip("0") or "0"
        yield number, unit


def extract_hard_tokens(text: str) -> frozenset[str]:
    """문장에서 숫자·수치 토큰만 뽑아 비교 가능한 형태로 정규화한다.

    숫자 바로 뒤의 한 글자 단위를 붙여 둔다("18일", "21%", "1237회").

    Args:
        text: 팩트 값이나 서술 문장

    Returns:
        정규화된 하드 토큰 집합. 숫자가 없으면 빈 집합.
    """
    return frozenset(
        f"{number}{unit}" for number, unit in _iter_number_tokens(text)
    )


def tokens_by_unit(text: str) -> dict[str, frozenset[str]]:
    """하드 토큰을 단위별로 묶는다 (단위 없는 숫자는 빈 문자열 키).

    단위별로 갈라 두면 "같은 종류의 값이 바뀌었는가"와 "다른 종류의 정보가
    덧붙었는가"를 구분할 수 있다.

    Args:
        text: 팩트 값이나 서술 문장

    Returns:
        단위 → 그 단위로 등장한 숫자 집합
    """
    grouped: dict[str, set[str]] = {}
    for number, unit in _iter_number_tokens(text):
        grouped.setdefault(unit, set()).add(number)
    return {unit: frozenset(numbers) for unit, numbers in grouped.items()}


def has_polarity_conflict(before: str, after: str) -> bool:
    """두 서술이 서로 반대되는 상태 어휘를 쓰는지 본다.

    같은 날짜에 "시행"이 "연기"로 바뀌는 경우처럼, 숫자는 그대로인데 상태만
    뒤집히는 진짜 변화를 하드 토큰 비교가 놓치지 않게 하는 보완 장치다.

    Args:
        before: 과거 값
        after: 오늘 값

    Returns:
        한쪽이 긍정 어휘만, 다른 쪽이 부정 어휘만 쓰면 True
    """
    for positive, negative in _POLARITY_GROUPS:
        before_positive = any(word in before for word in positive)
        before_negative = any(word in before for word in negative)
        after_positive = any(word in after for word in positive)
        after_negative = any(word in after for word in negative)
        if before_positive and not before_negative and after_negative and not after_positive:
            return True
        if before_negative and not before_positive and after_positive and not after_negative:
            return True
    return False


def is_restated_value(before: str, after: str) -> bool:
    """과거 값과 오늘 값이 같은 사실을 다시 쓴 것(패러프레이즈)인지 판정한다.

    판단할 수 없는 경우에는 **False를 돌려 억제하지 않는다**. 진짜 변경을
    지우는 쪽이 패러프레이즈 한 줄을 남기는 쪽보다 손해가 크기 때문이다.

    Args:
        before: DB에서 읽은 과거 팩트 값
        after: Diff worker가 뽑은 오늘 팩트 값

    Returns:
        실질 변화 없이 표현만 달라졌으면 True
    """
    before_text = (before or "").strip()
    after_text = (after or "").strip()
    if not before_text or not after_text:
        return False
    if before_text == after_text:
        return True
    before_units = tokens_by_unit(before_text)
    after_units = tokens_by_unit(after_text)
    # 양쪽 중 하나라도 숫자가 없으면 무엇이 "값"인지 코드가 알 수 없다.
    if not before_units or not after_units:
        return False
    # 과거 값에 있던 단위는 오늘 값에서도 숫자가 그대로여야 한다. 하나라도
    # 달라지거나 사라졌으면 실질이 바뀐 것이다.
    for unit, numbers in before_units.items():
        if after_units.get(unit) != numbers:
            return False
    return not has_polarity_conflict(before_text, after_text)
