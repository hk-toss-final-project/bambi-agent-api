"""수집 Scheduler 런타임의 구성·판정 루프를 검증한다.

실제 DB 연결 없이 Connection과 스케줄 기능을 대역으로 주입해, 설정에서
Scheduler를 구성하는 흐름·Provider별 실패 격리·상주 루프를 확인한다.

tick은 수집에서 끝나지 않고 본문 수집까지 이어지므로, 수집만 보는 테스트는
본문 수집 Batch를 대역으로 막아 네트워크·DB 접근을 없앤다.
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
    InterestRecalculationResult,
    MaintenanceRebuildResult,
    build_scheduler,
    run_collection_scheduler_loop,
)

_NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


class _FakeCursor:
    """execute 결과를 흉내 내는 Cursor 대역. 기본은 빈 결과다."""

    async def fetchone(self) -> None:
        """조회 결과가 없음을 나타낸다."""
        return None

    async def fetchall(self) -> list[Any]:
        """조회 결과가 없음을 나타낸다."""
        return []


class _FakeTransaction:
    """async with 문을 흉내 내는 Transaction 대역."""

    async def __aenter__(self) -> "_FakeTransaction":
        """Transaction 진입을 흉내 낸다."""
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        """Transaction 종료를 흉내 낸다."""
        return False


class _FakeConnection:
    """수동 실행 Job 처리에 필요한 최소 동작만 흉내 내는 Connection 대역."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        """연결 종료를 기록한다."""
        self.closed = True

    async def execute(self, *_args: Any, **_kwargs: Any) -> _FakeCursor:
        """SET LOCAL 등 부수 실행을 삼키고 빈 Cursor를 돌려준다."""
        return _FakeCursor()

    def transaction(self) -> _FakeTransaction:
        """Transaction async context manager 대역을 돌려준다."""
        return _FakeTransaction()


@pytest.fixture(autouse=True)
def _stub_manual_run_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    """수동 실행 Job Claim을 기본적으로 "없음"으로 만들어 drain을 무해화한다.

    drain을 직접 검증하는 테스트는 이 대역을 다시 덮어써 Job을 돌려주게 한다.
    """

    async def _no_jobs(*_args: Any, **_kwargs: Any) -> list[Any]:
        """점유할 수동 실행 Job이 없음을 나타낸다."""
        return []

    monkeypatch.setattr(runtime, "claim_runnable_agent_jobs", _no_jobs)


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


def _patch_content_fetch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fetched: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """본문 수집 Batch를 대역으로 바꾸고 호출 인자를 기록한다."""
    calls: list[dict[str, Any]] = []

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        """호출 인자를 기록하고 지정한 결과를 돌려준다."""
        calls.append(kwargs)
        return list(fetched or [])

    monkeypatch.setattr(runtime, "run_global_content_fetch_batch", _run)
    return calls


def _settings(**overrides: Any) -> Settings:
    """Scheduler 구성에 필요한 최소 설정을 만든다."""
    values: dict[str, Any] = {
        "agent_database_url": "postgresql://fake",
        "naver_client_id": "id",
        "naver_client_secret": SecretStr("secret"),
        "news_api_key": SecretStr("news-key"),
        "gdelt_base_url": "https://gdelt.example",
        "collection_scheduler_tick_seconds": 120,
        # 기본값과 다른 값을 명시해, 이 테스트가 "설정이 Scheduler로 전달되는가"를
        # 보게 한다. 기본값을 그대로 쓰면 기본값이 바뀔 때마다 테스트가 깨진다.
        "collection_content_fetch_limit": 7,
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
    assert scheduler.content_fetch_limit == 7
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
    _patch_content_fetch(monkeypatch)
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
    _patch_content_fetch(monkeypatch)

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


def test_run_once_fetches_pending_content_after_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """수집을 끝낸 tick이 이어서 본문 수집 Batch를 돌리는지 검증한다.

    수집은 URL만 저장하므로 이 단계가 빠지면 본문 없는 문서만 풀에 쌓인다.
    """
    connection = _FakeConnection()
    _patch_connection(monkeypatch, connection)
    calls = _patch_content_fetch(
        monkeypatch,
        fetched=[{"url": "https://a", "status": "completed"}],
    )
    monkeypatch.setattr(runtime, "PROVIDER_SCHEDULES", {"naver": _completed("naver")})

    results = asyncio.run(build_scheduler(_settings()).run_once(now=_NOW))

    assert calls == [{"database_url": "postgresql://fake", "limit": 7}]
    content = results[-1]
    assert content.provider == runtime.CONTENT_FETCH_STEP
    assert content.status == "completed"
    assert content.results == [{"url": "https://a", "status": "completed"}]


def test_run_once_skips_content_fetch_when_limit_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """본문 수집 건수를 0으로 끄면 Batch를 아예 부르지 않는지 검증한다."""
    connection = _FakeConnection()
    _patch_connection(monkeypatch, connection)
    calls = _patch_content_fetch(monkeypatch)
    monkeypatch.setattr(runtime, "PROVIDER_SCHEDULES", {"naver": _completed("naver")})

    settings = _settings(collection_content_fetch_limit=0)
    results = asyncio.run(build_scheduler(settings).run_once(now=_NOW))

    assert calls == []
    assert [result.provider for result in results] == ["naver"]


def test_run_once_isolates_content_fetch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """본문 수집이 실패해도 수집 결과가 살아남는지 검증한다.

    Jina Reader 장애로 tick 전체가 예외로 끝나면 정기 수집까지 함께 멈춘다.
    """
    connection = _FakeConnection()
    _patch_connection(monkeypatch, connection)

    async def _failing(**_kwargs: Any) -> list[dict[str, Any]]:
        """본문 수집 도중 예기치 못한 오류를 발생시킨다."""
        raise RuntimeError("Jina 장애")

    monkeypatch.setattr(runtime, "run_global_content_fetch_batch", _failing)
    monkeypatch.setattr(runtime, "PROVIDER_SCHEDULES", {"naver": _completed("naver")})

    results = asyncio.run(build_scheduler(_settings()).run_once(now=_NOW))

    assert results[0].status == "completed"
    content = results[-1]
    assert content.provider == runtime.CONTENT_FETCH_STEP
    assert content.status == "skipped"
    assert content.reason is not None and "Jina 장애" in content.reason


def test_scheduler_loop_runs_each_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    """상주 루프가 tick마다 판정을 실행하고 결과를 Callback으로 넘기는지 검증한다."""
    connection = _FakeConnection()
    _patch_connection(monkeypatch, connection)
    _patch_content_fetch(monkeypatch)
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


def test_run_once_drains_manual_collection_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """수동 실행 Job을 집어 정기 수집 경로로 돌리고 완료로 마감하는지 검증한다."""
    connection = _FakeConnection()
    _patch_connection(monkeypatch, connection)
    _patch_content_fetch(monkeypatch)
    # 정기 수집은 이 테스트의 관심이 아니므로 Provider 목록을 비운다.
    monkeypatch.setattr(runtime, "PROVIDER_SCHEDULES", {})

    claimed = runtime.ClaimedAgentJob(
        job_id="job-1",
        user_id=None,  # type: ignore[arg-type]
        feature_id="SCH-021",
        job_type=runtime.MANUAL_COLLECTION_JOB_TYPE,
        attempt_number=1,
        max_attempts=3,
        payload={"source_key": "interest-taxonomy-google-news"},
    )

    async def _claim(*_args: Any, **_kwargs: Any) -> list[Any]:
        """점유한 수동 실행 Job 하나를 돌려준다."""
        return [claimed]

    monkeypatch.setattr(runtime, "claim_runnable_agent_jobs", _claim)

    async def _fake_sch_021(
        _connection: Any, *, source_key: str, **_kwargs: Any
    ) -> tuple[None, list[CollectionScheduleResult]]:
        """수집 결과 한 건을 돌려주는 수동 실행 대역."""
        return (
            None,
            [
                CollectionScheduleResult(
                    provider="google_news",
                    source_key=source_key,
                    status="completed",
                    keyword="AI",
                    results=[
                        {
                            "provider": "google_news",
                            "status": "completed",
                            "fetched_count": 5,
                            "created_count": 3,
                            "duplicate_count": 2,
                        }
                    ],
                )
            ],
        )

    monkeypatch.setattr(runtime, "sch_021", _fake_sch_021)

    completed: list[tuple[str, dict[str, object]]] = []

    async def _complete(
        _connection: Any, *, job: Any, worker_id: str, result: dict[str, object]
    ) -> None:
        """완료 처리 인자를 기록한다."""
        completed.append((job.job_id, result))

    monkeypatch.setattr(runtime, "complete_agent_job", _complete)

    scheduler = build_scheduler(_settings())
    results = asyncio.run(scheduler.run_once(now=_NOW))

    # Job이 완료로 마감되고 요약이 저장된다.
    assert completed and completed[0][0] == "job-1"
    summary = completed[0][1]
    assert summary["source_key"] == "interest-taxonomy-google-news"
    assert summary["created_count"] == 3
    assert summary["status"] == "completed"
    # 결과 목록에도 수동 실행 단계가 완료로 남는다.
    manual = [item for item in results if item.provider == runtime.MANUAL_RUN_STEP]
    assert manual and manual[0].status == "completed"


def _patch_interest_recalculation(
    monkeypatch: pytest.MonkeyPatch, results: list[Any] | Exception
) -> list[dict[str, Any]]:
    """SCH-010 호출 인자를 기록하고 고정 결과를 돌려주도록 교체한다."""
    calls: list[dict[str, Any]] = []

    async def _fake_sch_010(_connection: Any, **kwargs: Any) -> list[Any]:
        """재계산 호출 인자를 기록하고 고정 결과를 돌려준다."""
        calls.append(kwargs)
        if isinstance(results, Exception):
            raise results
        return results

    monkeypatch.setattr(runtime, "sch_010", _fake_sch_010)
    return calls


def test_run_once_recalculates_stale_interests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tick이 수집을 끝낸 뒤 오래된 관심사 Profile을 다시 계산하는지 검증한다.

    이 단계가 없으면 저장이 멈춘 사용자의 관심사 점수가 마지막 Build 시점에
    고정돼 최신성 감쇠가 영영 반영되지 않는다.
    """
    connection = _FakeConnection()
    _patch_connection(monkeypatch, connection)
    _patch_content_fetch(monkeypatch)
    recalculated = InterestRecalculationResult(
        user_id="user-1", status="completed", version=5, interest_count=2
    )
    calls = _patch_interest_recalculation(monkeypatch, [recalculated])
    monkeypatch.setattr(runtime, "PROVIDER_SCHEDULES", {"naver": _completed("naver")})

    settings = _settings(
        interest_recalculation_limit=9,
        interest_recalculation_stale_hours=6.0,
    )
    results = asyncio.run(build_scheduler(settings).run_once(now=_NOW))

    assert calls == [{"stale_after_hours": 6.0, "limit": 9, "now": _NOW}]
    step = next(
        item
        for item in results
        if item.provider == runtime.INTEREST_RECALCULATION_STEP
    )
    assert step.status == "completed"
    assert step.results[0]["user_id"] == "user-1"
    assert step.results[0]["version"] == 5


def test_run_once_skips_interest_recalculation_when_limit_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """재계산 사용자 수를 0으로 끄면 SCH-010을 아예 부르지 않는지 검증한다."""
    connection = _FakeConnection()
    _patch_connection(monkeypatch, connection)
    _patch_content_fetch(monkeypatch)
    calls = _patch_interest_recalculation(monkeypatch, [])
    monkeypatch.setattr(runtime, "PROVIDER_SCHEDULES", {"naver": _completed("naver")})

    settings = _settings(interest_recalculation_limit=0)
    results = asyncio.run(build_scheduler(settings).run_once(now=_NOW))

    assert calls == []
    assert [result.provider for result in results] == ["naver"]


def test_run_once_isolates_interest_recalculation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """관심사 재계산이 실패해도 수집 결과와 tick이 살아남는지 검증한다."""
    connection = _FakeConnection()
    _patch_connection(monkeypatch, connection)
    _patch_content_fetch(monkeypatch)
    _patch_interest_recalculation(monkeypatch, RuntimeError("관심사 DB 장애"))
    monkeypatch.setattr(runtime, "PROVIDER_SCHEDULES", {"naver": _completed("naver")})

    settings = _settings(interest_recalculation_limit=5)
    results = asyncio.run(build_scheduler(settings).run_once(now=_NOW))

    naver = next(item for item in results if item.provider == "naver")
    assert naver.status == "completed"
    step = next(
        item
        for item in results
        if item.provider == runtime.INTEREST_RECALCULATION_STEP
    )
    assert step.status == "skipped"
    assert "관심사 DB 장애" in (step.reason or "")


def _patch_maintenance_rebuild(
    monkeypatch: pytest.MonkeyPatch, results: list[Any] | Exception
) -> list[dict[str, Any]]:
    """정기 재구성 등록 호출 인자를 기록하고 고정 결과를 돌려주도록 교체한다."""
    calls: list[dict[str, Any]] = []

    async def _fake_schedule(_connection: Any, **kwargs: Any) -> list[Any]:
        """등록 호출 인자를 기록하고 고정 결과를 돌려준다."""
        calls.append(kwargs)
        if isinstance(results, Exception):
            raise results
        return results

    monkeypatch.setattr(
        runtime, "schedule_personal_wiki_maintenance_rebuilds", _fake_schedule
    )
    return calls


def test_run_once_enqueues_maintenance_rebuilds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tick이 정기 Wiki 재구성 Job을 등록하는지 검증한다.

    증분 Build는 원본 유입에만 반응하므로, 이 단계가 없으면 누적된 중복·고아
    문서를 정리할 기회가 영영 오지 않는다.
    """
    connection = _FakeConnection()
    _patch_connection(monkeypatch, connection)
    _patch_content_fetch(monkeypatch)
    enqueued = MaintenanceRebuildResult(
        user_id="user-1", status="enqueued", job_id="job-1"
    )
    calls = _patch_maintenance_rebuild(monkeypatch, [enqueued])
    monkeypatch.setattr(runtime, "PROVIDER_SCHEDULES", {"naver": _completed("naver")})

    settings = _settings(
        maintenance_rebuild_limit=4,
        maintenance_rebuild_stale_hours=72.0,
    )
    results = asyncio.run(build_scheduler(settings).run_once(now=_NOW))

    assert calls == [{"stale_after_hours": 72.0, "limit": 4, "now": _NOW}]
    step = next(
        item for item in results if item.provider == runtime.MAINTENANCE_REBUILD_STEP
    )
    assert step.status == "completed"
    assert step.results[0]["job_id"] == "job-1"


def test_run_once_skips_maintenance_rebuild_when_limit_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """등록 수를 0으로 끄면 재구성 등록을 아예 부르지 않는지 검증한다."""
    connection = _FakeConnection()
    _patch_connection(monkeypatch, connection)
    _patch_content_fetch(monkeypatch)
    calls = _patch_maintenance_rebuild(monkeypatch, [])
    monkeypatch.setattr(runtime, "PROVIDER_SCHEDULES", {"naver": _completed("naver")})

    settings = _settings(maintenance_rebuild_limit=0)
    results = asyncio.run(build_scheduler(settings).run_once(now=_NOW))

    assert calls == []
    assert [result.provider for result in results] == ["naver"]


def test_run_once_isolates_maintenance_rebuild_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """재구성 등록이 실패해도 수집 결과와 tick이 살아남는지 검증한다."""
    connection = _FakeConnection()
    _patch_connection(monkeypatch, connection)
    _patch_content_fetch(monkeypatch)
    _patch_maintenance_rebuild(monkeypatch, RuntimeError("Job 등록 장애"))
    monkeypatch.setattr(runtime, "PROVIDER_SCHEDULES", {"naver": _completed("naver")})

    settings = _settings(maintenance_rebuild_limit=3)
    results = asyncio.run(build_scheduler(settings).run_once(now=_NOW))

    naver = next(item for item in results if item.provider == "naver")
    assert naver.status == "completed"
    step = next(
        item for item in results if item.provider == runtime.MAINTENANCE_REBUILD_STEP
    )
    assert step.status == "skipped"
    assert "Job 등록 장애" in (step.reason or "")
