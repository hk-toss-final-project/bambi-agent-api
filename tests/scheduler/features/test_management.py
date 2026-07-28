"""수집 스케줄 관리 기능(SCH-017·018·019·020·022)의 검증·변환을 확인한다.

실제 DB 없이 영속 함수를 대역으로 주입해, Cron·키워드 검증과 다음 실행 시각
계산, 없는 source_key 처리를 확인한다.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

import scheduler.features.management as management
from infrastructure.persistence.api import (
    GlobalCollectionRunRecord,
    GlobalCollectionSchedule,
)
from scheduler.api import (
    UnknownCollectionScheduleError,
    sch_017,
    sch_018,
    sch_019,
    sch_020,
    sch_022,
)


class _FakeConnection:
    """관리 기능은 영속 함수를 대역으로 바꾸므로 실제 실행이 없다."""


def _schedule(
    *,
    source_key: str = "latest-naver",
    provider: str = "naver",
    schedule_cron: str = "0 */6 * * *",
    keywords: tuple[str, ...] = ("코스피",),
    status: str = "active",
    last_started_at: datetime | None = None,
) -> GlobalCollectionSchedule:
    """테스트용 스케줄 설정 하나를 만든다."""
    return GlobalCollectionSchedule(
        source_id="source-1",
        source_key=source_key,
        provider=provider,
        schedule_cron=schedule_cron,
        keywords=keywords,
        language="ko",
        limit_per_provider=10,
        daily_max_runs=None,
        last_started_at=last_started_at,
        runs_today=0,
        status=status,
        display_name="Latest naver",
    )


def test_register_validates_and_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    """등록이 Cron·키워드를 정리해 영속 계층에 넘기는지 검증한다."""
    captured: dict[str, Any] = {}

    async def fake_upsert(_connection: Any, **kwargs: Any) -> GlobalCollectionSchedule:
        """Upsert 인자를 기록하고 저장 결과를 흉내 낸다."""
        captured.update(kwargs)
        return _schedule(keywords=tuple(kwargs["keywords"]))

    monkeypatch.setattr(management, "upsert_collection_schedule", fake_upsert)

    view = asyncio.run(
        sch_017(
            _FakeConnection(),  # type: ignore[arg-type]
            source_key="  latest-naver  ",
            provider="naver",
            schedule_cron="  0 */6 * * *  ",
            keywords=["코스피", "  ", " 삼성전자 "],
        )
    )

    assert captured["source_key"] == "latest-naver"
    assert captured["schedule_cron"] == "0 */6 * * *"
    assert captured["keywords"] == ["코스피", "삼성전자"]
    assert view.status == "active"
    assert view.cron_valid is True


def test_register_rejects_unsupported_provider() -> None:
    """정기 수집을 지원하지 않는 Provider는 거부하는지 검증한다."""
    with pytest.raises(ValueError, match="Provider"):
        asyncio.run(
            sch_017(
                _FakeConnection(),  # type: ignore[arg-type]
                source_key="latest-dart",
                provider="dart",
                schedule_cron="0 * * * *",
                keywords=["AI"],
            )
        )


def test_register_accepts_google_news(monkeypatch: pytest.MonkeyPatch) -> None:
    """RSS(google_news) Provider도 스케줄로 등록할 수 있는지 검증한다."""

    async def fake_upsert(_connection: Any, **kwargs: Any) -> GlobalCollectionSchedule:
        """저장 결과를 흉내 낸다."""
        return _schedule(source_key="latest-google_news", provider="google_news")

    monkeypatch.setattr(management, "upsert_collection_schedule", fake_upsert)

    view = asyncio.run(
        sch_017(
            _FakeConnection(),  # type: ignore[arg-type]
            source_key="latest-google_news",
            provider="google_news",
            schedule_cron="0 */6 * * *",
            keywords=["Cloudflare"],
        )
    )

    assert view.provider == "google_news"


def test_register_rejects_invalid_cron() -> None:
    """해석할 수 없는 Cron 식은 저장 전에 거부하는지 검증한다.

    잘못된 Cron이 저장되면 Scheduler가 매 tick 조용히 건너뛰기만 하므로,
    Service가 즉시 알 수 있도록 입력 시점에 막는다.
    """
    with pytest.raises(ValueError, match="schedule_cron"):
        asyncio.run(
            sch_017(
                _FakeConnection(),  # type: ignore[arg-type]
                source_key="latest-naver",
                provider="naver",
                schedule_cron="매시간",
                keywords=["AI"],
            )
        )


def test_register_rejects_empty_keywords() -> None:
    """공백뿐인 키워드 목록은 거부하는지 검증한다."""
    with pytest.raises(ValueError, match="키워드"):
        asyncio.run(
            sch_017(
                _FakeConnection(),  # type: ignore[arg-type]
                source_key="latest-naver",
                provider="naver",
                schedule_cron="0 * * * *",
                keywords=["  ", ""],
            )
        )


def test_update_reports_missing_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    """없는 source_key 수정은 전용 예외로 알리는지 검증한다."""

    async def fake_update(_connection: Any, **kwargs: Any) -> None:
        """대상이 없어 None을 돌려주는 상황을 흉내 낸다."""
        return None

    monkeypatch.setattr(management, "update_collection_schedule", fake_update)

    with pytest.raises(UnknownCollectionScheduleError):
        asyncio.run(
            sch_018(
                _FakeConnection(),  # type: ignore[arg-type]
                source_key="latest-unknown",
                schedule_cron="0 * * * *",
            )
        )


def test_update_keeps_unset_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """넘기지 않은 항목은 None으로 전달해 기존 값을 유지하는지 검증한다."""
    captured: dict[str, Any] = {}

    async def fake_update(_connection: Any, **kwargs: Any) -> GlobalCollectionSchedule:
        """수정 인자를 기록하고 변경 결과를 흉내 낸다."""
        captured.update(kwargs)
        return _schedule(schedule_cron="0 * * * *")

    monkeypatch.setattr(management, "update_collection_schedule", fake_update)

    asyncio.run(
        sch_018(
            _FakeConnection(),  # type: ignore[arg-type]
            source_key="latest-naver",
            schedule_cron="0 * * * *",
        )
    )

    assert captured["schedule_cron"] == "0 * * * *"
    assert captured["keywords"] is None
    assert captured["daily_max_runs"] is None


def test_pause_and_resume_set_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """중지·재개가 각각 paused·active 상태를 요청하는지 검증한다."""
    requested: list[str] = []

    async def fake_set_status(
        _connection: Any, *, source_key: str, status: str
    ) -> GlobalCollectionSchedule:
        """요청한 상태를 기록하고 그 상태의 스케줄을 돌려준다."""
        requested.append(status)
        return _schedule(status=status)

    monkeypatch.setattr(management, "set_collection_schedule_status", fake_set_status)

    paused = asyncio.run(
        sch_019(_FakeConnection(), source_key="latest-naver")  # type: ignore[arg-type]
    )
    resumed = asyncio.run(
        sch_020(_FakeConnection(), source_key="latest-naver")  # type: ignore[arg-type]
    )

    assert requested == ["paused", "active"]
    assert paused.status == "paused"
    assert resumed.status == "active"


def test_history_includes_paused_and_next_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """조회가 중지된 Source도 포함하고 다음 실행 시각을 계산하는지 검증한다."""

    async def fake_load(_connection: Any, **kwargs: Any) -> list[
        GlobalCollectionSchedule
    ]:
        """활성·중지 Source를 함께 돌려준다."""
        assert kwargs["only_scheduled"] is False
        return [
            _schedule(last_started_at=datetime(2026, 7, 28, 6, 0, tzinfo=UTC)),
            _schedule(source_key="latest-gdelt", provider="gdelt", status="paused"),
        ]

    async def fake_runs(_connection: Any, **kwargs: Any) -> list[
        GlobalCollectionRunRecord
    ]:
        """실행 이력 한 건을 돌려준다."""
        return [
            GlobalCollectionRunRecord(
                run_id="run-1",
                source_key="latest-naver",
                query="코스피",
                status="completed",
                fetched_count=10,
                created_count=10,
                duplicate_count=0,
                failed_count=0,
                error_code=None,
                started_at=datetime(2026, 7, 28, 6, 0, tzinfo=UTC),
                completed_at=datetime(2026, 7, 28, 6, 1, tzinfo=UTC),
            )
        ]

    monkeypatch.setattr(management, "load_collection_schedules", fake_load)
    monkeypatch.setattr(management, "load_collection_runs", fake_runs)

    schedules, runs = asyncio.run(sch_022(_FakeConnection()))  # type: ignore[arg-type]

    assert [schedule.status for schedule in schedules] == ["active", "paused"]
    assert schedules[0].next_run_at == datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    # 한 번도 실행하지 않은 Source는 다음 tick에 바로 도므로 예정 시각이 없다.
    assert schedules[1].next_run_at is None
    assert runs[0].created_count == 10


def test_history_reports_unknown_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """없는 source_key 조회는 전용 예외로 알리는지 검증한다."""

    async def fake_load(_connection: Any, **kwargs: Any) -> list[
        GlobalCollectionSchedule
    ]:
        """다른 Source만 등록된 상황을 흉내 낸다."""
        return [_schedule()]

    monkeypatch.setattr(management, "load_collection_schedules", fake_load)

    with pytest.raises(UnknownCollectionScheduleError):
        asyncio.run(
            sch_022(_FakeConnection(), source_key="latest-unknown")  # type: ignore[arg-type]
        )
