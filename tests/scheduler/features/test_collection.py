"""정기 수집 스케줄(SCH-002·SCH-003·SCH-004)의 판정과 실행을 검증한다.

실제 DB·외부 API 없이 스케줄 조회와 수집 Worker를 대역으로 주입하고, 판정
기준 시각을 인자로 넘겨 결과가 항상 결정적으로 나오게 한다.
"""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

import scheduler.features.collection as collection
from infrastructure.persistence.api import GlobalCollectionSchedule
from scheduler.api import (
    CollectionCredentials,
    next_collection_run_at,
    sch_001,
    sch_002,
    sch_003,
    sch_004,
)

_NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
# 마지막 실행이 11:00이고 주기가 6시간이면 다음 실행은 12:00이므로,
# 11:30은 "아직 차례가 아닌" 시각이다.
_BEFORE_NEXT_RUN = datetime(2026, 7, 28, 11, 30, tzinfo=UTC)
_CREDENTIALS = CollectionCredentials(
    naver_client_id="id",
    naver_client_secret="secret",
    news_api_key="news-key",
)


class _FakeConnection:
    """execute를 가진 최소한의 Connection 대역."""

    async def execute(self, query: str, params: Any = None) -> Any:
        """스케줄 조회는 대역 함수로 가로채므로 호출되지 않는다."""
        raise AssertionError("스케줄 조회는 대역으로 교체되어야 합니다.")


def _schedule(
    *,
    provider: str = "naver",
    schedule_cron: str = "0 */6 * * *",
    keywords: tuple[str, ...] = ("AI",),
    last_started_at: datetime | None = None,
    daily_max_runs: int | None = None,
    runs_today: int = 0,
    limit_per_provider: int = 10,
) -> GlobalCollectionSchedule:
    """테스트용 수집 스케줄 설정 하나를 만든다."""
    return GlobalCollectionSchedule(
        source_id=f"source-{provider}",
        source_key=f"latest-{provider}",
        provider=provider,
        schedule_cron=schedule_cron,
        keywords=keywords,
        language="ko",
        limit_per_provider=limit_per_provider,
        daily_max_runs=daily_max_runs,
        last_started_at=last_started_at,
        runs_today=runs_today,
    )


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    schedules: list[GlobalCollectionSchedule],
) -> list[dict[str, Any]]:
    """스케줄 조회와 수집 Worker를 대역으로 교체하고 호출 인자를 수집한다."""
    calls: list[dict[str, Any]] = []

    async def fake_load(_connection: Any) -> list[GlobalCollectionSchedule]:
        """등록된 스케줄 목록을 그대로 돌려준다."""
        return schedules

    async def fake_worker(**kwargs: Any) -> list[dict[str, object]]:
        """수집 Worker 호출 인자를 기록하고 완료 결과를 돌려준다."""
        calls.append(kwargs)
        return [{"provider": kwargs["providers"][0], "status": "completed"}]

    monkeypatch.setattr(collection, "load_collection_schedules", fake_load)
    monkeypatch.setattr(collection, "worker_001", fake_worker)
    return calls


def test_next_collection_run_at_follows_cron() -> None:
    """Cron 식과 기준 시각으로 다음 실행 시각을 계산하는지 검증한다."""
    assert next_collection_run_at("0 */6 * * *", after=_NOW) == datetime(
        2026, 7, 28, 18, 0, tzinfo=UTC
    )


def test_first_run_collects_without_waiting_for_cron(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """한 번도 수집한 적 없는 Source는 첫 주기를 기다리지 않고 수집하는지 검증한다."""
    calls = _patch(monkeypatch, [_schedule(last_started_at=None)])

    results = asyncio.run(
        sch_002(
            _FakeConnection(),  # type: ignore[arg-type]
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert [result.status for result in results] == ["completed"]
    assert results[0].source_key == "latest-naver"
    assert results[0].next_run_at == datetime(2026, 7, 28, 18, 0, tzinfo=UTC)
    assert calls[0]["keywords"] == ["AI"]
    assert calls[0]["providers"] == ["naver"]
    assert calls[0]["language"] == "ko"
    assert calls[0]["naver_client_id"] == "id"


def test_collection_records_run_under_the_requesting_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """수집 실행을 지시한 Source의 Key를 Worker로 넘기는지 검증한다.

    Provider 이름으로 되돌리면 실행 이력이 `latest-{provider}`에만 쌓여,
    Cron 주기·일일 한도 판정이 쓰는 마지막 실행 시각이 영영 비어 있게 된다.
    """
    schedule = _schedule(last_started_at=None)
    schedule = replace(schedule, source_key="interest-taxonomy-google-news")
    calls = _patch(monkeypatch, [schedule])

    asyncio.run(
        sch_002(
            _FakeConnection(),  # type: ignore[arg-type]
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert calls[0]["source_key"] == "interest-taxonomy-google-news"


def test_each_keyword_is_collected_as_its_own_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """키워드를 하나씩 따로 수집하는지 검증한다.

    수집 Worker는 키워드 목록을 공백으로 이어 붙여 단일 검색어를 만들기
    때문에, 여러 주제를 한 번에 넘기면 "코스피 삼성전자" 같은 질의가 되어
    0건으로 끝난다(협의안 §4.3 실측). 주제마다 따로 호출해야 한다.
    """
    calls = _patch(
        monkeypatch, [_schedule(keywords=("코스피", "삼성전자", "SK하이닉스"))]
    )

    results = asyncio.run(
        sch_002(
            _FakeConnection(),  # type: ignore[arg-type]
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert [call["keywords"] for call in calls] == [
        ["코스피"],
        ["삼성전자"],
        ["SK하이닉스"],
    ]
    assert [result.keyword for result in results] == [
        "코스피",
        "삼성전자",
        "SK하이닉스",
    ]
    assert all(result.status == "completed" for result in results)


def test_daily_quota_limits_number_of_keywords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """남은 일일 호출 여유만큼만 키워드를 수집하고 나머지는 건너뛰는지 검증한다."""
    calls = _patch(
        monkeypatch,
        [
            _schedule(
                keywords=("코스피", "삼성전자", "SK하이닉스"),
                daily_max_runs=4,
                runs_today=2,
            )
        ],
    )

    results = asyncio.run(
        sch_002(
            _FakeConnection(),  # type: ignore[arg-type]
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert [call["keywords"] for call in calls] == [["코스피"], ["삼성전자"]]
    assert [result.status for result in results] == [
        "completed",
        "completed",
        "skipped",
    ]
    assert results[2].keyword == "SK하이닉스"
    assert results[2].reason == "오늘 실행 한도 4회를 채웠습니다."


def test_skips_before_next_run_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """다음 실행 시각 전이면 수집하지 않고 사유를 남기는지 검증한다."""
    calls = _patch(
        monkeypatch,
        [_schedule(last_started_at=datetime(2026, 7, 28, 11, 0, tzinfo=UTC))],
    )

    results = asyncio.run(
        sch_002(
            _FakeConnection(),  # type: ignore[arg-type]
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_BEFORE_NEXT_RUN,
        )
    )

    assert results[0].status == "skipped"
    assert results[0].reason == "다음 실행 시각 전입니다."
    assert results[0].next_run_at == datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    assert calls == []


def test_collects_when_cron_time_has_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """마지막 실행 후 주기가 지났으면 수집을 실행하는지 검증한다."""
    calls = _patch(
        monkeypatch,
        [
            _schedule(
                provider="gdelt",
                last_started_at=datetime(2026, 7, 28, 5, 0, tzinfo=UTC),
                limit_per_provider=25,
            )
        ],
    )

    results = asyncio.run(
        sch_003(
            _FakeConnection(),  # type: ignore[arg-type]
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert results[0].status == "completed"
    assert calls[0]["providers"] == ["gdelt"]
    assert calls[0]["limit_per_provider"] == 25


def test_rss_schedule_collects_google_news(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RSS 수집 스케줄이 google_news Provider만 지정해 수집하는지 검증한다."""
    calls = _patch(
        monkeypatch, [_schedule(provider="google_news", keywords=("Cloudflare",))]
    )

    results = asyncio.run(
        sch_001(
            _FakeConnection(),  # type: ignore[arg-type]
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert results[0].status == "completed"
    assert calls[0]["providers"] == ["google_news"]
    assert calls[0]["keywords"] == ["Cloudflare"]


def test_force_skips_cron_but_keeps_daily_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """force는 실행 시각만 건너뛰고 일일 호출 한도는 그대로 지키는지 검증한다."""
    pending = _schedule(
        provider="newsapi",
        last_started_at=datetime(2026, 7, 28, 11, 0, tzinfo=UTC),
        daily_max_runs=2,
        runs_today=2,
    )
    calls = _patch(monkeypatch, [pending])

    blocked = asyncio.run(
        sch_004(
            _FakeConnection(),  # type: ignore[arg-type]
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_BEFORE_NEXT_RUN,
            force=True,
        )
    )

    assert blocked[0].status == "skipped"
    assert blocked[0].reason == "오늘 실행 한도 2회를 채웠습니다."
    assert calls == []

    allowed = _patch(
        monkeypatch,
        [
            _schedule(
                provider="newsapi",
                last_started_at=datetime(2026, 7, 28, 11, 0, tzinfo=UTC),
                daily_max_runs=2,
                runs_today=1,
            )
        ],
    )
    results = asyncio.run(
        sch_004(
            _FakeConnection(),  # type: ignore[arg-type]
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_BEFORE_NEXT_RUN,
            force=True,
        )
    )

    assert results[0].status == "completed"
    assert allowed[0]["news_api_key"] == "news-key"


def test_skips_source_without_keywords(monkeypatch: pytest.MonkeyPatch) -> None:
    """키워드가 비어 있으면 Worker를 호출하지 않고 건너뛰는지 검증한다.

    Worker는 키워드가 없으면 ValueError로 죽으므로, Scheduler가 먼저 걸러야
    한 Source 설정 누락이 전체 tick을 실패시키지 않는다.
    """
    calls = _patch(monkeypatch, [_schedule(keywords=())])

    results = asyncio.run(
        sch_002(
            _FakeConnection(),  # type: ignore[arg-type]
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert results[0].status == "skipped"
    assert results[0].reason == "수집 키워드가 비어 있습니다."
    assert calls == []


def test_skips_invalid_cron_expression(monkeypatch: pytest.MonkeyPatch) -> None:
    """해석할 수 없는 Cron 식은 예외 없이 건너뛰는지 검증한다."""
    calls = _patch(
        monkeypatch,
        [
            _schedule(
                schedule_cron="매시간",
                last_started_at=datetime(2026, 7, 28, 5, 0, tzinfo=UTC),
            )
        ],
    )

    results = asyncio.run(
        sch_002(
            _FakeConnection(),  # type: ignore[arg-type]
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert results[0].status == "skipped"
    assert results[0].reason is not None
    assert "schedule_cron" in results[0].reason
    assert calls == []


def test_reports_not_configured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """해당 Provider의 활성 스케줄이 없으면 not_configured로 알리는지 검증한다."""
    calls = _patch(monkeypatch, [_schedule(provider="gdelt")])

    results = asyncio.run(
        sch_002(
            _FakeConnection(),  # type: ignore[arg-type]
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert results[0].status == "not_configured"
    assert results[0].source_key is None
    assert calls == []


def test_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """database_url이 없으면 ValueError를 발생시키는지 검증한다."""
    _patch(monkeypatch, [_schedule()])

    with pytest.raises(ValueError):
        asyncio.run(
            sch_002(
                _FakeConnection(),  # type: ignore[arg-type]
                database_url="",
                credentials=_CREDENTIALS,
                now=_NOW,
            )
        )
