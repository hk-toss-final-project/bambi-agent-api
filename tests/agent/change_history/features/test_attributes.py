"""팩트 이름표 안정성 검사(attributes.py) 단위 테스트.

정상 이름표 케이스는 2026-08-11 운영 DB에 실제로 저장된 값을 그대로 옮겨 왔다.
오탐(정상 이름표를 불안정으로 잡는 것)이 없어야 재작업 비용이 새지 않는다.
"""

from __future__ import annotations

import pytest

from agent.change_history.features.attributes import (
    find_drifting_marker,
    is_stable_attribute,
)


@pytest.mark.parametrize(
    "attribute",
    [
        "제1237회",
        "1237회",
        "2026년 목표",
        "3분기 실적",
        "8월 판매량",
        "18일 시행 계획",
        "3주차 성적",
    ],
)
def test_drifting_markers_are_unstable(attribute: str) -> None:
    """날짜·회차가 박힌 이름표는 불안정으로 잡는다."""
    assert is_stable_attribute(attribute) is False
    assert find_drifting_marker(attribute) is not None


@pytest.mark.parametrize(
    "attribute",
    [
        "미수령 당첨금 자동 지급 시스템",
        "4등 및 5등 당첨금 자동입금 시스템",
        "양산 일정",
        "등락률",
        "가격",
    ],
)
def test_stable_labels_are_not_flagged(attribute: str) -> None:
    """숫자가 범주의 일부인 정상 이름표는 잡지 않는다(오탐 방지)."""
    assert is_stable_attribute(attribute) is True
    assert find_drifting_marker(attribute) is None


def test_found_marker_is_reported_for_the_message() -> None:
    """교정 지시에 쓸 수 있도록 발견한 조각을 그대로 돌려준다."""
    assert find_drifting_marker("제1237회") == "제1237회"


def test_blank_attribute_is_treated_as_stable() -> None:
    """빈 이름표는 다른 검증이 다루므로 여기서는 통과시킨다."""
    assert is_stable_attribute("") is True
    assert find_drifting_marker("   ") is None
