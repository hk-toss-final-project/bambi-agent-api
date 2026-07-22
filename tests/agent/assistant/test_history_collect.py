"""수집 이력(history의 collect_history) 검증. 이력 파일은 임시 디렉터리로 격리한다."""

from datetime import UTC, datetime, timedelta

import pytest

from agent.assistant.features import history

_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolate_history(tmp_path, monkeypatch):
    """이력 파일 경로를 임시 디렉터리로 돌려 실제 data/를 건드리지 않는다."""


def test_cold_start_detection() -> None:
    """수집 이력이 없으면 콜드 스타트로 판정한다."""
    assert history.has_collect_history("minji", "전고체") is False

    history.record_collected("minji", "전고체", "https://a.com/1", "기사", "https://a.com/1", first_seen=_NOW)

    assert history.has_collect_history("minji", "전고체") is True


def test_first_seen_is_not_overwritten() -> None:
    """같은 URL을 다시 기록해도 first_seen(최초 발견 시각)은 유지된다."""
    first = history.record_collected(
        "minji", "전고체", "https://a.com/1", "기사", "https://a.com/1", first_seen=_NOW
    )
    second = history.record_collected(
        "minji", "전고체", "https://a.com/1", "기사", "https://a.com/1", first_seen=_NOW + timedelta(days=1)
    )

    assert first == second == _NOW
    assert history.get_first_seen("minji", "전고체", "https://a.com/1") == _NOW


def test_score_is_updated_but_kept_when_omitted() -> None:
    """score는 최신 계산값으로 갱신하되, 생략하면 기존 값을 유지한다."""
    history.record_collected("minji", "전고체", "https://a.com/1", "기사", "https://a.com/1", first_seen=_NOW, score=0.4)
    history.record_collected("minji", "전고체", "https://a.com/1", "기사", "https://a.com/1", first_seen=_NOW, score=0.7)

    assert history.get_collected_entries("minji", "전고체")["https://a.com/1"]["score"] == 0.7

    history.record_collected("minji", "전고체", "https://a.com/1", "기사", "https://a.com/1", first_seen=_NOW)

    assert history.get_collected_entries("minji", "전고체")["https://a.com/1"]["score"] == 0.7


def test_get_first_seen_missing_returns_none() -> None:
    """기록이 없는 URL의 first_seen은 None이다."""
    assert history.get_first_seen("minji", "전고체", "https://a.com/none") is None
