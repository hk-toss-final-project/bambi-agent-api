"""보고서 중복 방지(dedup) 검증. 이력 파일은 임시 디렉터리로 격리한다."""

from datetime import UTC, datetime, timedelta

import pytest

from agent.assistant.features import dedup

_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolate_history(tmp_path, monkeypatch):
    """이력 파일 경로를 임시 디렉터리로 돌려 실제 data/를 건드리지 않는다."""
    monkeypatch.setattr(dedup, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(dedup, "_REPORT_EMBEDDING_PATH", tmp_path / "report_embedding_history.json")


def _record(url_key: str, embedding: list[float], reported_at: datetime) -> None:
    """지정한 시각으로 보고 이력 한 건을 기록한다."""
    dedup.record_report_items(
        "minji", "전고체", [{"url_key": url_key, "title": url_key, "embedding": embedding}], now=reported_at
    )


def test_load_excludes_items_older_than_lookback() -> None:
    """DEDUP_LOOKBACK_DAYS(7일)보다 오래된 이력은 중복 검사 대상에서 뺀다."""
    _record("https://a.com/old", [1.0, 0.0], _NOW - timedelta(days=10))
    _record("https://a.com/recent", [0.0, 1.0], _NOW - timedelta(days=2))

    items = dedup.load_recent_report_items("minji", "전고체", now=_NOW)

    assert [item["url_key"] for item in items] == ["https://a.com/recent"]


def test_load_excludes_today_for_idempotency() -> None:
    """같은 날 기록된 항목은 제외해, 당일 재실행이 스스로와 중복 처리되지 않게 한다."""
    _record("https://a.com/today", [1.0, 0.0], _NOW - timedelta(hours=1))
    _record("https://a.com/yesterday", [0.0, 1.0], _NOW - timedelta(days=1))

    items = dedup.load_recent_report_items("minji", "전고체", now=_NOW)

    assert [item["url_key"] for item in items] == ["https://a.com/yesterday"]


def test_check_duplicate_below_threshold_is_new() -> None:
    """유사도가 DUP_THRESHOLD 미만이면 신규다."""
    _record("https://a.com/1", [1.0, 0.0], _NOW - timedelta(days=1))
    history = dedup.load_recent_report_items("minji", "전고체", now=_NOW)

    status, _, sim = dedup.check_duplicate([0.0, 1.0], _NOW, history)

    assert status == dedup.STATUS_NEW
    assert sim < dedup.config.DUP_THRESHOLD


def test_check_duplicate_near_identical_is_duplicate() -> None:
    """유사도가 DUP_STRICT_THRESHOLD 이상이면 발행일과 무관하게 중복이다."""
    _record("https://a.com/1", [1.0, 0.0], _NOW - timedelta(days=1))
    history = dedup.load_recent_report_items("minji", "전고체", now=_NOW)

    status, matched, sim = dedup.check_duplicate([1.0, 0.0], _NOW, history)

    assert status == dedup.STATUS_DUPLICATE
    assert matched is not None and matched["url_key"] == "https://a.com/1"
    assert sim == pytest.approx(1.0)


def test_check_duplicate_followup_is_update() -> None:
    """중간 유사도(0.85~0.95)이고 기존 보고 이후 발행이면 후속 업데이트로 본다."""
    _record("https://a.com/1", [0.9, 0.436], _NOW - timedelta(days=1))
    history = dedup.load_recent_report_items("minji", "전고체", now=_NOW)

    # cos([1,0],[0.9,0.436]) ≈ 0.9 → 임계 구간, 발행일이 보고 이후 → 업데이트
    status, _, sim = dedup.check_duplicate([1.0, 0.0], _NOW, history)

    assert 0.85 <= sim < 0.95
    assert status == dedup.STATUS_UPDATE


def test_check_duplicate_followup_without_newer_date_is_duplicate() -> None:
    """중간 유사도라도 발행일이 기존 보고 이전(또는 미상)이면 중복으로 본다."""
    _record("https://a.com/1", [0.9, 0.436], _NOW - timedelta(days=1))
    history = dedup.load_recent_report_items("minji", "전고체", now=_NOW)

    older = _NOW - timedelta(days=3)
    assert dedup.check_duplicate([1.0, 0.0], older, history)[0] == dedup.STATUS_DUPLICATE
    assert dedup.check_duplicate([1.0, 0.0], None, history)[0] == dedup.STATUS_DUPLICATE


def test_record_overwrites_same_url_key() -> None:
    """같은 url_key는 덮어써서 재실행해도 이력이 불어나지 않는다 (멱등성)."""
    _record("https://a.com/1", [1.0, 0.0], _NOW - timedelta(days=1))
    _record("https://a.com/1", [1.0, 0.0], _NOW - timedelta(days=1))

    items = dedup.load_recent_report_items("minji", "전고체", now=_NOW)

    assert len(items) == 1


def test_record_prunes_expired_entries() -> None:
    """기록 시점에 룩백을 벗어난 옛 항목을 청소한다."""
    _record("https://a.com/old", [1.0, 0.0], _NOW - timedelta(days=30))
    _record("https://a.com/new", [0.0, 1.0], _NOW)

    data = dedup._load()
    keyword_entry = data["minji"]["전고체"]

    assert "https://a.com/old" not in keyword_entry
    assert "https://a.com/new" in keyword_entry
