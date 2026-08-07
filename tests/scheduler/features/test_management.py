"""수집 스케줄 관리 기능(SCH-017·018·019·020·021·022)의 검증·변환을 확인한다.

실제 DB 없이 영속 함수를 대역으로 주입해, Cron·키워드 검증과 다음 실행 시각
계산, 없는 source_key 처리를 확인한다. 수동 실행(SCH-021)은 수집 Worker까지
대역으로 바꿔 외부 API 호출 없이 판정만 확인한다.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

import scheduler.features.collection as collection
import scheduler.features.management as management
from infrastructure.persistence.api import (
    CollectionTargetPlan,
    GlobalCollectionRunRecord,
    GlobalCollectionSchedule,
)
from scheduler.api import (
    CollectionCredentials,
    UnknownCollectionScheduleError,
    sch_017,
    sch_018,
    sch_019,
    sch_020,
    sch_021,
    sch_022,
)

_NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
_CREDENTIALS = CollectionCredentials(
    naver_client_id="id", naver_client_secret="secret"
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
    daily_max_runs: int | None = None,
    runs_today: int = 0,
    search_options: dict[str, Any] | None = None,
    targets: tuple[CollectionTargetPlan, ...] = (),
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
        daily_max_runs=daily_max_runs,
        last_started_at=last_started_at,
        runs_today=runs_today,
        status=status,
        display_name="Latest naver",
        search_options=search_options or {},
        targets=targets,
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


def test_register_accepts_sns_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """YouTube·Reddit도 정기 수집 스케줄로 등록할 수 있는지 검증한다."""
    for name in ("youtube", "reddit"):

        async def fake_upsert(
            _connection: Any, **kwargs: Any
        ) -> GlobalCollectionSchedule:
            """저장 결과를 흉내 낸다."""
            return _schedule(
                source_key=kwargs["source_key"], provider=kwargs["provider"]
            )

        monkeypatch.setattr(management, "upsert_collection_schedule", fake_upsert)

        view = asyncio.run(
            sch_017(
                _FakeConnection(),  # type: ignore[arg-type]
                source_key=f"latest-{name}",
                provider=name,
                schedule_cron="0 */6 * * *",
                keywords=["후쿠오카"],
            )
        )

        assert view.provider == name


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


def _patch_manual_run(
    monkeypatch: pytest.MonkeyPatch, schedule: GlobalCollectionSchedule | None
) -> list[dict[str, Any]]:
    """수동 실행이 쓰는 스케줄 조회와 수집 Worker를 대역으로 교체한다."""
    calls: list[dict[str, Any]] = []

    async def fake_load(
        _connection: Any, *, source_key: str
    ) -> GlobalCollectionSchedule | None:
        """등록된 스케줄 하나를 그대로 돌려준다."""
        return schedule

    async def fake_worker(**kwargs: Any) -> list[dict[str, object]]:
        """수집 Worker 호출 인자를 기록하고 완료 결과를 돌려준다."""
        calls.append(kwargs)
        return [
            {
                "provider": kwargs["providers"][0],
                "status": "completed",
                "created_count": 3,
            }
        ]

    monkeypatch.setattr(management, "load_collection_schedule", fake_load)
    monkeypatch.setattr(collection, "worker_001", fake_worker)
    return calls


def test_manual_run_ignores_cron_and_collects_each_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """수동 실행이 다음 실행 시각 전에도 키워드를 각각 수집하는지 검증한다."""
    calls = _patch_manual_run(
        monkeypatch,
        _schedule(
            keywords=("코스피", "삼성전자"),
            # 30분 전에 실행했으므로 6시간 주기로는 아직 차례가 아니다.
            last_started_at=datetime(2026, 7, 29, 11, 30, tzinfo=UTC),
        ),
    )

    view, results = asyncio.run(
        sch_021(
            _FakeConnection(),  # type: ignore[arg-type]
            source_key="latest-naver",
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert [result.status for result in results] == ["completed", "completed"]
    assert [call["keywords"] for call in calls] == [["코스피"], ["삼성전자"]]
    assert calls[0]["providers"] == ["naver"]
    assert calls[0]["naver_client_id"] == "id"
    assert view.source_key == "latest-naver"


def test_manual_run_runs_paused_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    """중지된 스케줄도 수동 실행은 수집하는지 검증한다.

    중지는 정기 실행만 멈춘다. 수동 실행은 관리자가 명시적으로 지시한 별개
    행위이므로 상태를 이유로 막지 않는다.
    """
    calls = _patch_manual_run(monkeypatch, _schedule(status="paused"))

    _, results = asyncio.run(
        sch_021(
            _FakeConnection(),  # type: ignore[arg-type]
            source_key="latest-naver",
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert [result.status for result in results] == ["completed"]
    assert len(calls) == 1


def test_manual_run_ignores_daily_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """수동 실행이 일일 실행 한도에 막히지 않는지 검증한다.

    한도는 "알아서 도는 수집"을 통제하는 장치다. 관리자가 지금 결과를 보겠다고
    명시한 요청까지 막으면 한도가 낮은 스케줄은 점검이 불가능해진다.
    """
    calls = _patch_manual_run(
        monkeypatch,
        _schedule(keywords=("후쿠오카", "르센느"), daily_max_runs=1, runs_today=1),
    )

    _, results = asyncio.run(
        sch_021(
            _FakeConnection(),  # type: ignore[arg-type]
            source_key="latest-naver",
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert [result.status for result in results] == ["completed", "completed"]
    assert [call["keywords"] for call in calls] == [["후쿠오카"], ["르센느"]]


def test_manual_run_reports_empty_keywords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """키워드가 없는 스케줄은 수집하지 않고 사유를 남기는지 검증한다."""
    calls = _patch_manual_run(monkeypatch, _schedule(keywords=()))

    _, results = asyncio.run(
        sch_021(
            _FakeConnection(),  # type: ignore[arg-type]
            source_key="latest-naver",
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert results[0].status == "skipped"
    assert "키워드" in (results[0].reason or "")
    assert calls == []


def test_manual_run_collects_interest_topics_without_fixed_keywords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """고정 키워드가 없어도 관심 Topic이 있으면 수동 실행이 수집한다.

    검색어를 전부 관심 Topic으로 받는 스케줄(interest-taxonomy-google-news)이
    "키워드가 비어 있다"며 건너뛰던 문제다. 정기 실행은 멀쩡히 돌던 스케줄이라
    점검하러 이 버튼을 누른 사람이 더 헷갈린다(2026-08-06 실측).
    """
    calls = _patch_manual_run(
        monkeypatch,
        _schedule(
            keywords=(),
            targets=(
                CollectionTargetPlan(target_key="custom:abc", query="리튬황 배터리"),
            ),
        ),
    )

    _, results = asyncio.run(
        sch_021(
            _FakeConnection(),  # type: ignore[arg-type]
            source_key="latest-naver",
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert [result.status for result in results] == ["completed"]
    assert [call["keywords"] for call in calls] == [["리튬황 배터리"]]


def test_manual_run_collects_topics_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """수동 실행이 관심 Topic 검색을 동시에 수집하는지 검증한다.

    관심 Topic이 많은 taxonomy Source는 검색이 수십 개로 불어나, 순차로 돌면
    응답이 분 단위로 늦어진다(2026-08-07 실측: google_news RSS 74회 이상, 5분
    초과). 검색을 동시에 수집하되 동시 실행 수는 상한을 넘지 않아야 한다.
    """
    targets = tuple(
        CollectionTargetPlan(target_key=f"topic-{index}", query=f"주제{index}")
        for index in range(10)
    )
    schedule = _schedule(
        source_key="interest-taxonomy-google-news",
        provider="google_news",
        keywords=(),
        targets=targets,
    )

    inflight = 0
    max_inflight = 0

    async def fake_load(
        _connection: Any, *, source_key: str
    ) -> GlobalCollectionSchedule:
        """등록된 taxonomy 스케줄을 그대로 돌려준다."""
        return schedule

    async def fake_worker(**kwargs: Any) -> list[dict[str, object]]:
        """동시에 진행 중인 검색 수를 관찰하며 완료 결과를 돌려준다."""
        nonlocal inflight, max_inflight
        inflight += 1
        max_inflight = max(max_inflight, inflight)
        # 다른 검색이 동시에 진입할 틈을 준다. 순차라면 항상 1을 넘지 못한다.
        await asyncio.sleep(0)
        inflight -= 1
        return [{"provider": kwargs["providers"][0], "status": "completed"}]

    monkeypatch.setattr(management, "load_collection_schedule", fake_load)
    monkeypatch.setattr(collection, "worker_001", fake_worker)

    _, results = asyncio.run(
        sch_021(
            _FakeConnection(),  # type: ignore[arg-type]
            source_key="interest-taxonomy-google-news",
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    # 모든 Topic이 수집되고, 결과 순서는 계획 순서와 같다(gather는 순서 보존).
    assert [result.keyword for result in results] == [
        f"주제{index}" for index in range(10)
    ]
    assert all(result.status == "completed" for result in results)
    # 동시에 여러 검색이 진행되지만 상한을 넘지 않는다.
    assert max_inflight > 1
    assert max_inflight <= collection.MANUAL_RUN_CONCURRENCY


def test_manual_run_reports_unknown_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """없는 source_key 수동 실행은 전용 예외로 알리는지 검증한다."""
    _patch_manual_run(monkeypatch, None)

    with pytest.raises(UnknownCollectionScheduleError):
        asyncio.run(
            sch_021(
                _FakeConnection(),  # type: ignore[arg-type]
                source_key="latest-unknown",
                database_url="postgresql://fake",
                credentials=_CREDENTIALS,
                now=_NOW,
            )
        )


def test_manual_run_rejects_unsupported_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """정기 수집을 지원하지 않는 Provider는 수동 실행도 거부하는지 검증한다."""
    _patch_manual_run(monkeypatch, _schedule(provider="dart"))

    with pytest.raises(ValueError, match="Provider"):
        asyncio.run(
            sch_021(
                _FakeConnection(),  # type: ignore[arg-type]
                source_key="latest-dart",
                database_url="postgresql://fake",
                credentials=_CREDENTIALS,
                now=_NOW,
            )
        )


def test_manual_run_passes_source_search_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source에 설정한 검색 범위·정렬이 수집 Worker까지 전달되는지 검증한다.

    이 배선이 끊기면 Source별 서브레딧 화이트리스트가 조용히 무시되고 Reddit
    전체 검색으로 되돌아간다.
    """
    calls = _patch_manual_run(
        monkeypatch,
        _schedule(
            source_key="latest-reddit",
            provider="reddit",
            search_options={"subreddits": ["MachineLearning"], "time_filter": "day"},
        ),
    )

    asyncio.run(
        management.sch_021(
            _FakeConnection(),
            source_key="latest-reddit",
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert calls[0]["search_options"] == {
        "subreddits": ["MachineLearning"],
        "time_filter": "day",
    }
