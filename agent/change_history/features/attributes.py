"""팩트 이름표(attribute)의 안정성 검사 (LLM 호출 없음, 무료·결정적).

`attribute`는 **날이 바뀌어도 그대로인 이름표**여야 한다. 대조는 (subject,
attribute)로 하므로, 이름표에 날짜·회차 같은 흐르는 값이 섞이면 내일 같은
사실을 찾지 못한다. 같은 사실이 매번 신규로 쌓이고 델타는 영원히 "전부 새 소식"이
된다 — 기능이 조용히 죽는 실패 방식이라 겉으로 드러나지 않는다.

diff.py 프롬프트가 이 규칙을 명시하는데도 실측에서 무너졌다.

    2026-08-11 운영 DB — subject='로또', attribute='제1237회'

회차 번호가 이름표에 박혀 다음 회차(제1238회)에는 절대 매칭되지 않는다.

**판정은 흐르는 시점·순번 표기에만 건다.** 숫자가 있다는 이유만으로 걸면
'4등 및 5등 당첨금'처럼 숫자가 범주의 일부인 정상 이름표까지 잡힌다(실측 확인).
잡아내는 정확도를 넓히기보다, 확실한 것만 잡아 오탐을 만들지 않는 쪽을 택한다.
"""

from __future__ import annotations

import re

# 날이 바뀌면 값이 흐르는 시점·순번 표기. 이름표에 들어가면 대조가 끊긴다.
#   제1237회 / 1237회 / 2026년 / 3분기 / 8월 / 18일 / 3주차
_DRIFTING_MARKERS = (
    re.compile(r"제?\s*\d+\s*회"),
    re.compile(r"\d{4}\s*년"),
    re.compile(r"\d+\s*분기"),
    re.compile(r"\d+\s*개?월"),
    re.compile(r"\d+\s*일"),
    re.compile(r"\d+\s*주\s*차"),
)


def find_drifting_marker(attribute: str) -> str | None:
    """이름표에 섞인 시점·순번 표기를 찾아 그 조각을 돌려준다.

    Args:
        attribute: 검사할 팩트 이름표

    Returns:
        발견한 표기 조각. 없으면 None.
    """
    text = (attribute or "").strip()
    if not text:
        return None
    for pattern in _DRIFTING_MARKERS:
        found = pattern.search(text)
        if found:
            return found.group(0).strip()
    return None


def is_stable_attribute(attribute: str) -> bool:
    """이름표가 날짜·회차에 흔들리지 않고 내일도 같은 값인지 판정한다.

    Args:
        attribute: 검사할 팩트 이름표

    Returns:
        흐르는 시점·순번 표기가 없으면 True
    """
    return find_drifting_marker(attribute) is None
