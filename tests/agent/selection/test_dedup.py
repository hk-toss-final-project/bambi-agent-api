"""보고서 중복 방지(dedup) 검증. 이력 저장소는 임시 디렉터리로 격리해 주입한다."""

from datetime import UTC, datetime, timedelta

import pytest

from agent.assistant.features import storage
from agent.selection.features import dedup

_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)

# 주입된 이력 저장소. 선별은 저장소를 직접 만들지 않고 호출자에게 받는다.
_STORE = None


@pytest.fixture(autouse=True)
def _isolate_history(tmp_path):
    """이력 저장소를 임시 디렉터리 기반으로 만들어 실제 data/를 건드리지 않는다."""
    global _STORE
    _STORE = storage.JsonHistoryStore(tmp_path)
    yield
    _STORE = None


def _record(url_key: str, embedding: list[float], reported_at: datetime) -> None:
    """지정한 시각으로 보고 이력 한 건을 기록한다."""
    dedup.record_report_items(
        "minji",
        "전고체",
        [{"url_key": url_key, "title": url_key, "embedding": embedding}],
        history=_STORE,
        now=reported_at,
    )


def _load(**kwargs) -> list[dict[str, object]]:
    """주입된 저장소에서 최근 보고 이력을 조회한다."""
    return dedup.load_recent_report_items("minji", "전고체", history=_STORE, **kwargs)


def test_load_excludes_items_older_than_lookback() -> None:
    """DEDUP_LOOKBACK_DAYS(7일)보다 오래된 이력은 중복 검사 대상에서 뺀다."""
    _record("https://a.com/old", [1.0, 0.0], _NOW - timedelta(days=10))
    _record("https://a.com/recent", [0.0, 1.0], _NOW - timedelta(days=2))

    items = _load(now=_NOW)

    assert [item["url_key"] for item in items] == ["https://a.com/recent"]


def test_load_excludes_today_for_idempotency() -> None:
    """같은 날 기록된 항목은 제외해, 당일 재실행이 스스로와 중복 처리되지 않게 한다."""
    _record("https://a.com/today", [1.0, 0.0], _NOW - timedelta(hours=1))
    _record("https://a.com/yesterday", [0.0, 1.0], _NOW - timedelta(days=1))

    items = _load(now=_NOW)

    assert [item["url_key"] for item in items] == ["https://a.com/yesterday"]


def test_check_duplicate_below_threshold_is_new() -> None:
    """유사도가 DUP_THRESHOLD 미만이면 신규다."""
    _record("https://a.com/1", [1.0, 0.0], _NOW - timedelta(days=1))
    history = _load(now=_NOW)

    status, _, sim = dedup.check_duplicate([0.0, 1.0], _NOW, history)

    assert status == dedup.STATUS_NEW
    assert sim < dedup.config.DUP_THRESHOLD


def test_check_duplicate_near_identical_is_duplicate() -> None:
    """유사도가 DUP_STRICT_THRESHOLD 이상이면 발행일과 무관하게 중복이다."""
    _record("https://a.com/1", [1.0, 0.0], _NOW - timedelta(days=1))
    history = _load(now=_NOW)

    status, matched, sim = dedup.check_duplicate([1.0, 0.0], _NOW, history)

    assert status == dedup.STATUS_DUPLICATE
    assert matched is not None and matched["url_key"] == "https://a.com/1"
    assert sim == pytest.approx(1.0)


def test_check_duplicate_followup_is_update() -> None:
    """중간 유사도(0.85~0.95)이고 기존 보고 이후 발행이면 후속 업데이트로 본다."""
    _record("https://a.com/1", [0.9, 0.436], _NOW - timedelta(days=1))
    history = _load(now=_NOW)

    # cos([1,0],[0.9,0.436]) ≈ 0.9 → 임계 구간, 발행일이 보고 이후 → 업데이트
    status, _, sim = dedup.check_duplicate([1.0, 0.0], _NOW, history)

    assert 0.85 <= sim < 0.95
    assert status == dedup.STATUS_UPDATE


def test_check_duplicate_followup_without_newer_date_is_duplicate() -> None:
    """중간 유사도라도 발행일이 기존 보고 이전(또는 미상)이면 중복으로 본다."""
    _record("https://a.com/1", [0.9, 0.436], _NOW - timedelta(days=1))
    history = _load(now=_NOW)

    older = _NOW - timedelta(days=3)
    assert dedup.check_duplicate([1.0, 0.0], older, history)[0] == dedup.STATUS_DUPLICATE
    assert dedup.check_duplicate([1.0, 0.0], None, history)[0] == dedup.STATUS_DUPLICATE


def test_record_overwrites_same_url_key() -> None:
    """같은 url_key는 덮어써서 재실행해도 이력이 불어나지 않는다 (멱등성)."""
    _record("https://a.com/1", [1.0, 0.0], _NOW - timedelta(days=1))
    _record("https://a.com/1", [1.0, 0.0], _NOW - timedelta(days=1))

    items = _load(now=_NOW)

    assert len(items) == 1


def test_record_prunes_expired_entries() -> None:
    """기록 시점에 룩백을 벗어난 옛 항목을 청소한다."""
    _record("https://a.com/old", [1.0, 0.0], _NOW - timedelta(days=30))
    _record("https://a.com/new", [0.0, 1.0], _NOW)

    # 룩백을 넉넉히 잡아도 옛 항목은 이미 삭제돼 조회되지 않는다.
    remaining = {
        item["url_key"]
        for item in _load(now=_NOW, lookback_days=365, exclude_today=False)
    }

    assert "https://a.com/old" not in remaining
    assert "https://a.com/new" in remaining


def test_record_without_history_store_writes_nothing() -> None:
    """이력 저장소를 안 넘기면 기록하지 않는다.

    리포트 생성처럼 사용자의 브리핑 이력을 건드리면 안 되는 소비자를 위한
    구조적 안전장치다 — 플래그를 깜빡해도 기록할 수단 자체가 없어야 한다.
    """
    dedup.record_report_items(
        "minji",
        "전고체",
        [{"url_key": "https://a.com/1", "title": "t", "embedding": [1.0, 0.0]}],
        history=None,
        now=_NOW - timedelta(days=1),
    )

    assert _load(now=_NOW, exclude_today=False) == []


def test_load_without_history_store_returns_empty() -> None:
    """이력 저장소를 안 넘기면 조회도 하지 않는다(중복 검사 없이 전부 신규)."""
    _record("https://a.com/1", [1.0, 0.0], _NOW - timedelta(days=1))

    assert dedup.load_recent_report_items("minji", "전고체", now=_NOW) == []
