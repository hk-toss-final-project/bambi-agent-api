"""델타 기준일 시간대 설정을 검증한다.

기준일은 타임라인의 절대 날짜로 사용자에게 그대로 보이므로, UTC가 아니라
서비스 시간대에서 본 날짜여야 한다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from agent.change_history.api import current_reference_date, reference_timezone


def test_reference_date_uses_kst_by_default() -> None:
    """환경변수가 없으면 KST 기준 날짜를 돌려준다.

    UTC 22:00은 KST로 다음 날 07:00이다. 아침 브리핑이 도는 시간대라
    여기서 UTC를 쓰면 날짜가 하루 밀린다.
    """
    moment = datetime(2026, 8, 10, 22, 0, tzinfo=UTC)

    assert current_reference_date(moment) == date(2026, 8, 11)


def test_reference_date_keeps_the_same_day_within_kst_business_hours() -> None:
    """KST 낮 시간대는 UTC 기준과 같은 날짜가 나온다(회귀 확인)."""
    moment = datetime(2026, 8, 11, 3, 0, tzinfo=UTC)  # KST 12:00

    assert current_reference_date(moment) == date(2026, 8, 11)


def test_naive_datetime_is_treated_as_utc() -> None:
    """시간대 없는 시각도 UTC로 보고 변환한다."""
    assert current_reference_date(datetime(2026, 8, 10, 22, 0)) == date(2026, 8, 11)


def test_environment_variable_overrides_the_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """다른 지역에 배포하면 IANA 이름으로 시간대를 바꿀 수 있다."""
    monkeypatch.setenv("CHANGE_HISTORY_REFERENCE_TIMEZONE", "UTC")

    assert current_reference_date(datetime(2026, 8, 10, 22, 0, tzinfo=UTC)) == date(
        2026, 8, 10
    )


def test_unknown_timezone_falls_back_to_kst(monkeypatch: pytest.MonkeyPatch) -> None:
    """이름이 잘못돼도 UTC로 떨어지지 않고 KST로 되돌아간다.

    여기서 UTC로 폴백하면 고치려던 날짜 밀림이 조용히 되살아난다.
    """
    monkeypatch.setenv("CHANGE_HISTORY_REFERENCE_TIMEZONE", "Mars/Olympus")

    assert reference_timezone().utcoffset(None) == timedelta(hours=9)
    assert current_reference_date(datetime(2026, 8, 10, 22, 0, tzinfo=UTC)) == date(
        2026, 8, 11
    )


def test_aware_datetime_in_another_zone_is_converted() -> None:
    """다른 시간대의 시각을 받아도 서비스 시간대로 환산한다."""
    moment = datetime(2026, 8, 10, 18, 0, tzinfo=timezone(timedelta(hours=-4)))

    assert current_reference_date(moment) == date(2026, 8, 11)
