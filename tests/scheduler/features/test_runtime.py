"""수집 Scheduler 런타임의 구성·판정 루프를 검증한다.

실제 DB 연결 없이 Connection과 스케줄 기능을 대역으로 주입해, 설정에서
Scheduler를 구성하는 흐름·Provider별 실패 격리·상주 루프를 확인한다.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import SecretStr

import scheduler.features.runtime as runtime
from app.config import Settings
from scheduler.api import (
    CollectionCredentials,
    CollectionScheduleResult,
    build_scheduler,
    run_collection_scheduler_loop,
)

_NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


class _FakeConnection:
    """close만 기록하는 Connection 대역."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        """연결 종료를 기록한다."""
        self.closed = True


def _patch_connection(
    monkeypatch: pytest.MonkeyPatch, connection: _FakeConnection
) -> None:
    """AsyncConnection.connect가 주어진 대역 연결을 반환하도록 교체한다."""

    class _FakeAsyncConnection:
        @classmethod
        async def connect(cls, *args: Any, **kwargs: Any) -> _FakeConnection:
            """대역 연결을 반환한다."""
            return connection

    monkeypatch.setattr(runtime, "AsyncConnection", _FakeAsyncConnection)


def _settings(**overrides: Any) -> Settings:
    """Scheduler 구성에 필요한 최소 설정을 만든다."""
    values: dict[str, Any] = {
        "agent_database_url": "postgresql://fake",
        "naver_client_id": "id",
        "naver_client_secret": SecretStr("secret"),
        "news_api_key": SecretStr("news-key"),
        "gdelt_base_url": "https://gdelt.example",
        "collection_scheduler_tick_seconds": 120,
    }
    values.update(overrides)
    return Settings(**values)


def _completed(provider: str):
    """호출 사실을 기록하지 않고 완료 결과만 돌려주는 스케줄 기능 대역."""

    async def _run(_connection: Any, **kwargs: Any) -> list[CollectionScheduleResult]:
        """완료 결과 한 건을 돌려준다."""
        return [
            CollectionScheduleResult(
                provider=provider,
                source_key=f"latest-{provider}",
                status="completed",
            )
        ]

    return _run


def test_build_scheduler_reads_credentials_from_settings() -> None:
    """설정의 자격 증명과 tick 간격을 Scheduler로 옮기는지 검증한다."""
    scheduler = build_scheduler(_settings())

    assert scheduler.database_url == "postgresql://fake"
    assert scheduler.tick_seconds == 120
    assert scheduler.credentials == CollectionCredentials(
        naver_client_id="id",
        naver_client_secret="secret",
        gdelt_base_url="https://gdelt.example",
        news_api_key="news-key",
    )


def test_build_scheduler_requires_database_url() -> None:
    """AGENT_DATABASE_URL이 없으면 RuntimeError를 발생시키는지 검증한다."""
    with pytest.raises(RuntimeError):
        build_scheduler(_settings(agent_database_url=None))


def test_run_once_collects_every_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """등록된 Provider 세 개를 모두 판정하고 연결을 닫는지 검증한다."""
    connection = _FakeConnection()
    _patch_connection(monkeypatch, connection)
    called: list[str] = []

    def _recording(provider: str):
        """Provider 이름을 기록하는 스케줄 기능 대역을 만든다."""

        async def _run(
            _connection: Any, **kwargs: Any
        ) -> list[CollectionScheduleResult]:
            """호출 사실을 기록하고 완료 결과를 돌려준다."""
            called.append(provider)
            return [
                CollectionScheduleResult(
                    provider=provider,
                    source_key=f"latest-{provider}",
                    status="completed",
                )
            ]

        return _run

    monkeypatch.setattr(
        runtime,
        "PROVIDER_SCHEDULES",
        {
            name: _recording(name)
            for name in ("naver", "gdelt", "newsapi", "google_news")
        },
    )

    scheduler = build_scheduler(_settings())
    results = asyncio.run(scheduler.run_once(now=_NOW))

    assert called == ["naver", "gdelt", "newsapi", "google_news"]
    assert [result.status for result in results] == ["completed"] * 4
    assert connection.closed is True


def test_every_scheduled_provider_has_a_feature() -> None:
    """스케줄 대상 Provider와 실행 기능 매핑이 어긋나지 않는지 검증한다.

    Provider를 추가하면서 한쪽만 고치면, 스케줄 등록은 되는데 tick에서 아무도
    실행하지 않는 Source가 조용히 생긴다.
    """
    from scheduler.api import PROVIDER_SCHEDULES, SCHEDULED_PROVIDERS

    assert set(PROVIDER_SCHEDULES) == set(SCHEDULED_PROVIDERS)


def test_run_once_isolates_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """한 Provider가 예외로 죽어도 나머지 Provider 수집이 계속되는지 검증한다."""
    connection = _FakeConnection()
    _patch_connection(monkeypatch, connection)

    async def _failing(_connection: Any, **kwargs: Any) -> list[
        CollectionScheduleResult
    ]:
        """수집 도중 예기치 못한 오류를 발생시킨다."""
        raise RuntimeError("Naver API 장애")

    monkeypatch.setattr(
        runtime,
        "PROVIDER_SCHEDULES",
        {"naver": _failing, "gdelt": _completed("gdelt")},
    )

    scheduler = build_scheduler(_settings())
    results = asyncio.run(scheduler.run_once(now=_NOW))

    naver = next(result for result in results if result.provider == "naver")
    gdelt = next(result for result in results if result.provider == "gdelt")
    assert naver.status == "skipped"
    assert naver.reason is not None
    assert "SCH-002" in naver.reason
    assert "Naver API 장애" in naver.reason
    assert gdelt.status == "completed"
    assert connection.closed is True


def test_scheduler_loop_runs_each_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    """상주 루프가 tick마다 판정을 실행하고 결과를 Callback으로 넘기는지 검증한다."""
    connection = _FakeConnection()
    _patch_connection(monkeypatch, connection)
    monkeypatch.setattr(runtime, "PROVIDER_SCHEDULES", {"naver": _completed("naver")})
    ticks: list[list[CollectionScheduleResult]] = []

    asyncio.run(
        run_collection_scheduler_loop(
            build_scheduler(_settings()),
            tick_seconds=0,
            max_ticks=3,
            on_tick=ticks.append,
        )
    )

    assert len(ticks) == 3
    assert all(tick[0].status == "completed" for tick in ticks)


class _FlakyScheduler:
    """첫 tick만 실패하는 Scheduler 대역."""

    tick_seconds = 0

    def __init__(self) -> None:
        self.attempts = 0

    async def run_once(self, **kwargs: Any) -> list[CollectionScheduleResult]:
        """첫 호출만 예외를 던지고 이후에는 완료 결과를 돌려준다."""
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("DB 연결 실패")
        return [
            CollectionScheduleResult(
                provider="naver", source_key="latest-naver", status="completed"
            )
        ]


def test_scheduler_loop_survives_tick_failure() -> None:
    """tick 하나가 통째로 실패해도 루프가 죽지 않고 다음 tick을 도는지 검증한다.

    DB가 잠깐 끊기면 run_once 자체가 예외로 끝난다. 그때 Scheduler가 영영
    멈추면 서버를 재시작해야 수집이 되살아나므로, 루프는 유지되어야 한다.
    """
    scheduler = _FlakyScheduler()
    ticks: list[list[CollectionScheduleResult]] = []

    asyncio.run(
        run_collection_scheduler_loop(
            scheduler,  # type: ignore[arg-type]
            tick_seconds=0,
            max_ticks=2,
            on_tick=ticks.append,
        )
    )

    assert scheduler.attempts == 2
    # 실패한 tick은 Callback을 부르지 않고, 성공한 tick만 결과를 넘긴다.
    assert len(ticks) == 1
