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
from infrastructure.persistence.api import (
    CollectionTargetPlan,
    GlobalCollectionSchedule,
)
from scheduler.api import (
    CollectionCredentials,
    next_collection_run_at,
    plan_schedule_queries,
    plan_target_queries,
    sch_001,
    sch_002,
    sch_003,
    sch_004,
    split_collection_budget,
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
    targets: tuple[CollectionTargetPlan, ...] = (),
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
        targets=targets,
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


def test_budget_split_keeps_total_and_reserves_label_share() -> None:
    """수집 예산을 라벨과 확장 검색어에 나누되 총량을 늘리지 않는지 검증한다.

    본문 수집 처리량이 병목이라 총량이 늘면 본문 없는 문서만 쌓인다.
    """
    # 기본 설정: 10건 예산에 큐레이션 키워드 6개 → 라벨 4 + 키워드 6×1 = 10
    assert split_collection_budget(10, 6) == (4, 1)
    # 예산이 늘면 키워드 몫이 먼저 는다.
    assert split_collection_budget(20, 6) == (8, 2)
    # 키워드가 없으면 예전처럼 라벨이 전부 가져간다.
    assert split_collection_budget(10, 0) == (10, 0)
    # 예산이 0이면 아무 검색도 돌리지 않는다.
    assert split_collection_budget(0, 6) == (0, 0)


def test_target_plan_puts_label_first_and_tags_every_query_with_topic() -> None:
    """라벨 검색을 먼저 돌리고, 모든 검색 결과를 같은 Topic에 귀속시킨다.

    확장 검색어로 모은 문서도 같은 target_key를 달아야, 사용자가 고른 라벨로
    리포트를 만들 때 그 자료를 찾을 수 있다.
    """
    target = CollectionTargetPlan(
        target_key="taxonomy:v1:space",
        query="우주·천문",
        keywords=("우주", "천문", "위성", "화성", "NASA", "스페이스X"),
    )

    queries = plan_target_queries(target, limit=10)

    assert queries[0].query == "우주·천문"
    assert queries[0].limit == 4
    assert [q.query for q in queries[1:]] == [
        "우주",
        "천문",
        "위성",
        "화성",
        "NASA",
        "스페이스X",
    ]
    assert all(q.limit == 1 for q in queries[1:])
    # 어느 검색어로 모았든 같은 Topic에 묶인다.
    assert {q.target_key for q in queries} == {"taxonomy:v1:space"}
    # 총 수집량은 예산 그대로다.
    assert sum(q.limit for q in queries) == 10


def test_target_plan_skips_keyword_identical_to_label() -> None:
    """라벨과 글자가 같은 키워드는 같은 검색을 두 번 돌리므로 건너뛴다."""
    target = CollectionTargetPlan(
        target_key="taxonomy:v1:game",
        query="게임",
        keywords=("게임", "e스포츠"),
    )

    queries = plan_target_queries(target, limit=10)

    assert [q.query for q in queries] == ["게임", "e스포츠"]


def test_target_without_keywords_falls_back_to_label_only() -> None:
    """큐레이션 키워드가 없는 Topic(custom 등)은 예전처럼 라벨만 검색한다."""
    target = CollectionTargetPlan(target_key="custom:abc", query="사내 위키")

    queries = plan_target_queries(target, limit=10)

    assert len(queries) == 1
    assert queries[0].query == "사내 위키"
    assert queries[0].limit == 10
    assert queries[0].target_key == "custom:abc"


def test_source_keywords_have_no_topic_and_keep_full_limit() -> None:
    """Source 고정 키워드는 Topic 귀속이 없고 예산도 나누지 않는다."""
    schedule = _schedule(
        keywords=("Cloudflare", "코스피"),
        targets=(
            CollectionTargetPlan(
                target_key="taxonomy:v1:ai",
                query="AI·머신러닝",
                keywords=("LLM", "OpenAI"),
            ),
        ),
    )

    queries = plan_schedule_queries(schedule)

    fixed = [q for q in queries if q.target_key is None]
    assert [q.query for q in fixed] == ["Cloudflare", "코스피"]
    assert all(q.limit == 10 for q in fixed)

    topical = [q for q in queries if q.target_key == "taxonomy:v1:ai"]
    assert [q.query for q in topical] == ["AI·머신러닝", "LLM", "OpenAI"]
    assert sum(q.limit for q in topical) == 10


def test_topic_collection_passes_target_key_and_split_limit_to_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Topic 수집이 Worker에 target_key와 나눈 예산을 전달하는지 검증한다."""
    schedule = _schedule(
        provider="google_news",
        keywords=(),
        targets=(
            CollectionTargetPlan(
                target_key="taxonomy:v1:space",
                query="우주·천문",
                keywords=("스페이스X",),
            ),
        ),
    )
    calls = _patch(monkeypatch, [schedule])

    asyncio.run(
        sch_001(
            _FakeConnection(),
            database_url="postgresql://fake",
            credentials=_CREDENTIALS,
            now=_NOW,
        )
    )

    assert [call["keywords"] for call in calls] == [["우주·천문"], ["스페이스X"]]
    assert [call["target_key"] for call in calls] == [
        "taxonomy:v1:space",
        "taxonomy:v1:space",
    ]
    # 키워드가 적으면 그만큼 몫이 커진다 — 라벨 7 + 키워드 3 = 10으로 총량 유지.
    assert [call["limit_per_provider"] for call in calls] == [7, 3]
    assert sum(call["limit_per_provider"] for call in calls) == 10


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
