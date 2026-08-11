"""갱신 판정의 실질 변화 재확인(values.py) 단위 테스트.

케이스는 2026-08-11 운영 DB에서 실제로 오탐이 난 팩트를 그대로 옮겨 왔다.
LLM을 호출하지 않으므로 항상 무료·결정적으로 통과해야 한다.
"""

from __future__ import annotations

import pytest

from agent.change_history.features.values import (
    extract_hard_tokens,
    has_polarity_conflict,
    is_restated_value,
    tokens_by_unit,
)


def test_tokens_are_grouped_by_unit() -> None:
    """단위별로 숫자를 묶고, 단위 없는 숫자는 빈 문자열 키에 모은다."""
    assert tokens_by_unit("오는 18일부터 4등과 5등") == {
        "일": frozenset({"18"}),
        "등": frozenset({"4", "5"}),
    }
    assert tokens_by_unit("3거래일 만에 21% 급등") == {
        "": frozenset({"3"}),
        "%": frozenset({"21"}),
    }
    assert tokens_by_unit("숫자 없음") == {}


def test_added_detail_in_a_new_unit_is_restated() -> None:
    """과거 단위의 숫자가 그대로면 새 단위로 덧붙은 세부는 재서술로 본다.

    2026-08-11 벤치 `dup_expanded`: 시행일(18일)은 그대로인데 4등·5등 설명이
    붙어 단순 집합 비교로는 빠져나갔다.
    """
    before = "18일부터 시행된다."
    after = (
        "오는 18일부터 판매점에서 구매한 종이 로또복권을 간편결제 앱 페이코에 "
        "등록하면 4등과 5등 소액 당첨금이 자동으로 입금된다."
    )
    assert is_restated_value(before, after) is True


def test_extra_number_in_the_same_unit_is_not_restated() -> None:
    """같은 단위에 숫자가 늘면 진짜 변경으로 남긴다(부분집합 비교의 함정)."""
    assert is_restated_value("18일부터 시행된다.", "18일 발표, 시행은 25일부터.") is False


def test_dropped_unit_is_not_restated() -> None:
    """과거에 있던 단위가 오늘 값에서 사라지면 억제하지 않는다."""
    assert is_restated_value("1,500억원 규모", "2조원 규모로 확대") is False


def test_hard_tokens_normalize_separators_and_units() -> None:
    """쉼표·앞자리 0을 없애고 숫자 뒤 한 글자 단위만 붙인다."""
    assert extract_hard_tokens("오는 18일부터 시행된다.") == frozenset({"18일"})
    assert extract_hard_tokens("제1237회 당첨") == frozenset({"1237회"})
    assert extract_hard_tokens("3거래일 만에 21% 급등") == frozenset({"3", "21%"})
    assert extract_hard_tokens("1,500억원 규모") == frozenset({"1500억"})
    assert extract_hard_tokens("08일 발표") == frozenset({"8일"})


def test_hard_tokens_are_empty_without_numbers() -> None:
    """숫자가 없으면 빈 집합을 돌려준다."""
    assert extract_hard_tokens("시행이 연기되었다.") == frozenset()
    assert extract_hard_tokens("") == frozenset()


def test_particle_only_difference_is_restated() -> None:
    """조사 하나만 붙은 재서술을 패러프레이즈로 잡는다 (실측 04:18 → 06:07)."""
    assert is_restated_value("오는 18일부터 시행된다.", "18일부터 시행된다.") is True


def test_expanded_sentence_is_restated() -> None:
    """같은 사실을 길게 풀어 쓴 재서술을 잡는다 (실측 11:11 → 11:33)."""
    before = (
        "오는 18일부터 판매점에서 구매한 종이 로또복권을 간편결제 앱 '페이코'에 "
        "등록하면 당첨금을 자동으로 입금받을 수 있게 된다."
    )
    after = (
        "오는 18일부터 판매점에서 구매한 종이 로또복권을 간편결제 앱 '페이코'에 "
        "등록하면, 당첨금을 자동으로 입금받을 수 있는 시스템이 시행된다."
    )
    assert is_restated_value(before, after) is True


def test_summarized_sentence_is_restated() -> None:
    """긴 문장을 짧게 요약한 재서술도 하드 토큰이 같으면 잡는다."""
    before = (
        "오는 18일부터 판매점에서 구매한 종이 로또복권을 간편결제 앱 '페이코'에 "
        "등록하면 당첨금을 자동으로 입금받을 수 있게 된다."
    )
    assert is_restated_value(before, "18일부터 시행된다.") is True


def test_identical_text_is_restated() -> None:
    """글자까지 같은 값은 그대로 패러프레이즈다."""
    assert is_restated_value("18일부터 시행된다.", "18일부터 시행된다.") is True


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("오는 18일부터 시행된다.", "오는 20일부터 시행된다."),
        ("3거래일 만에 21% 급등", "5거래일 만에 30% 급등"),
        ("1,500억원 규모", "2,000억원 규모"),
    ],
)
def test_changed_numbers_are_not_restated(before: str, after: str) -> None:
    """수치·날짜가 실제로 달라지면 억제하지 않는다."""
    assert is_restated_value(before, after) is False


def test_polarity_flip_with_same_date_is_not_restated() -> None:
    """숫자가 같아도 상태가 뒤집히면 진짜 변화로 남긴다."""
    assert is_restated_value("18일부터 시행된다.", "18일부터 연기된다.") is False


def test_added_status_word_alone_is_not_a_conflict() -> None:
    """한쪽에만 상태 어휘가 붙은 것은 상충이 아니다(재서술 과정에서 흔히 붙는다)."""
    assert has_polarity_conflict("당첨금을 자동으로 입금받을 수 있게 된다.", "시스템이 시행된다.") is False
    assert has_polarity_conflict("시행된다.", "연기된다.") is True


def test_value_without_numbers_is_left_to_the_llm_verdict() -> None:
    """숫자가 없어 판단 근거가 없으면 억제하지 않는다."""
    assert is_restated_value("시행이 확정되었다.", "시행이 확정된 상태다.") is False


def test_empty_side_is_not_restated() -> None:
    """한쪽이 비어 있으면 비교할 수 없으므로 억제하지 않는다."""
    assert is_restated_value("", "18일부터 시행된다.") is False
    assert is_restated_value("18일부터 시행된다.", "   ") is False
