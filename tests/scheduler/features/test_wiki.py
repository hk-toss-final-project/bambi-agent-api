"""SCH-009 Wiki Build 스케줄 조정과 SCH-010 관심사 주기 재계산을 검증한다."""

import asyncio
from typing import Any

import pytest
from pytest import MonkeyPatch

from domain.interests.api import ActiveWikiRequiredError
from scheduler.features import wiki as wiki_scheduler
from scheduler.features.wiki import sch_009, sch_010


class _FakeCursor:
    """fetchall을 지원하는 결정적 Cursor Test Double."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        """조회 시 반환할 고정 Row 목록을 보관한다."""
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        """전체 Row 목록을 반환한다."""
        return self._rows


class _FakeConnection:
    """SQL 실행 내역과 순서별 응답을 기록하는 Connection Test Double."""

    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        """순서별 응답과 빈 SQL 실행 내역을 초기화한다."""
        self._responses = responses
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    async def execute(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> _FakeCursor:
        """SQL을 기록하고 순서별 고정 Cursor를 반환한다."""
        self.executed.append((query, params))
        rows = self._responses.pop(0) if self._responses else []
        return _FakeCursor(rows)


def test_sch_009_defers_pending_jobs_with_policy_minutes() -> None:
    """defer 동작이 조용 시간과 최대 대기시간으로 대기 Job을 미룬다."""
    connection = _FakeConnection([[{"id": "job-1"}, {"id": "job-2"}]])

    result = asyncio.run(
        sch_009(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            action="defer",
            quiet_minutes=10,
            max_wait_minutes=30,
        )
    )

    assert result.action == "defer"
    assert result.affected_jobs == 2
    assert connection.executed[0][1] == ("user-1", 30, 10)


def test_sch_009_releases_pending_jobs_for_forced_build() -> None:
    """release 동작이 강제 실행을 위해 대기 Job을 즉시 실행 가능으로 바꾼다."""
    connection = _FakeConnection([[{"id": "job-1"}]])

    result = asyncio.run(
        sch_009(
            connection,  # type: ignore[arg-type]
            user_id="user-1",
            action="release",
        )
    )

    assert result.action == "release"
    assert result.affected_jobs == 1
    assert "scheduled_at = clock_timestamp()" in connection.executed[0][0]


def test_sch_009_validates_required_inputs() -> None:
    """connection·user_id·action·대기시간 입력을 실행 전에 검증한다."""
    connection = _FakeConnection([])

    with pytest.raises(ValueError, match="connection"):
        asyncio.run(
            sch_009(
                None,  # type: ignore[arg-type]
                user_id="user-1",
            )
        )
    with pytest.raises(ValueError, match="user_id"):
        asyncio.run(
            sch_009(
                connection,  # type: ignore[arg-type]
                user_id="",
            )
        )
    with pytest.raises(ValueError, match="action"):
        asyncio.run(
            sch_009(
                connection,  # type: ignore[arg-type]
                user_id="user-1",
                action="rebuild",  # type: ignore[arg-type]
            )
        )
    with pytest.raises(ValueError, match="허용 범위"):
        asyncio.run(
            sch_009(
                connection,  # type: ignore[arg-type]
                user_id="user-1",
                quiet_minutes=-1,
                max_wait_minutes=30,
            )
        )


def _stub_recalculation(
    monkeypatch: MonkeyPatch,
    *,
    users: list[str],
    profiles: dict[str, Any] | None = None,
    subscribed: list[str] | None = None,
) -> dict[str, Any]:
    """SCH-010이 호출하는 조회·재계산·수집 갱신을 결정적 대역으로 바꾼다."""
    calls: dict[str, Any] = {"int_011": [], "sync": [], "list": []}

    async def fake_list(connection: object, **kwargs: object) -> list[str]:
        """재계산 대상 조회 인자를 기록하고 고정 사용자 목록을 반환한다."""
        calls["list"].append(kwargs)
        return users

    async def fake_int_011(repository: object, user_id: str, **_: object) -> Any:
        """사용자별 재계산 결과를 고정 Profile로 반환한다."""
        calls["int_011"].append(user_id)
        result = (profiles or {}).get(user_id, {"version": 3, "interests": []})
        if isinstance(result, Exception):
            raise result
        return result

    async def fake_sync(
        connection: object, *, user_id: str, interests: object
    ) -> list[str]:
        """수집 대상 갱신 인자를 기록하고 고정 목록을 반환한다."""
        calls["sync"].append(user_id)
        return list(subscribed or [])

    monkeypatch.setattr(
        wiki_scheduler, "list_users_for_interest_recalculation", fake_list
    )
    monkeypatch.setattr(wiki_scheduler, "int_011", fake_int_011)
    monkeypatch.setattr(
        wiki_scheduler, "sync_wiki_interest_collection_targets", fake_sync
    )
    return calls


def test_sch_010_recalculates_every_stale_user(monkeypatch: MonkeyPatch) -> None:
    """대상 사용자마다 관심사를 다시 계산하고 결과를 보고한다."""
    calls = _stub_recalculation(
        monkeypatch,
        users=["user-1", "user-2"],
        profiles={
            "user-1": {"version": 7, "interests": [{"topic": "날씨"}]},
            "user-2": {"version": 2, "interests": []},
        },
        subscribed=["날씨"],
    )

    results = asyncio.run(sch_010(object()))  # type: ignore[arg-type]

    assert calls["int_011"] == ["user-1", "user-2"]
    assert [item.status for item in results] == ["completed", "completed"]
    assert results[0].version == 7
    assert results[0].interest_count == 1
    assert results[0].subscribed_targets == ("날씨",)


def test_sch_010_passes_policy_to_target_query(monkeypatch: MonkeyPatch) -> None:
    """경과 시간·최대 사용자 수 정책을 대상 조회에 그대로 넘긴다."""
    calls = _stub_recalculation(monkeypatch, users=[])

    asyncio.run(
        sch_010(
            object(),  # type: ignore[arg-type]
            stale_after_hours=6.0,
            limit=3,
        )
    )

    assert calls["list"][0]["stale_after_hours"] == 6.0
    assert calls["list"][0]["limit"] == 3


def test_sch_010_isolates_one_user_failure(monkeypatch: MonkeyPatch) -> None:
    """사용자 한 명의 재계산 실패가 나머지 사용자를 막지 않는다."""
    calls = _stub_recalculation(
        monkeypatch,
        users=["user-1", "user-2"],
        profiles={
            "user-1": RuntimeError("DB 연결 끊김"),
            "user-2": {"version": 4, "interests": []},
        },
    )

    results = asyncio.run(sch_010(object()))  # type: ignore[arg-type]

    assert calls["int_011"] == ["user-1", "user-2"]
    assert results[0].status == "failed"
    assert "DB 연결 끊김" in (results[0].reason or "")
    assert results[1].status == "completed"


def test_sch_010_treats_missing_wiki_as_skipped(monkeypatch: MonkeyPatch) -> None:
    """조회 후 Wiki가 사라진 사용자는 실패가 아니라 건너뜀으로 본다."""
    _stub_recalculation(
        monkeypatch,
        users=["user-1"],
        profiles={"user-1": ActiveWikiRequiredError("활성 Wiki 없음")},
    )

    results = asyncio.run(sch_010(object()))  # type: ignore[arg-type]

    assert results[0].status == "skipped"


def test_sch_010_keeps_profile_when_target_sync_fails(
    monkeypatch: MonkeyPatch,
) -> None:
    """수집 대상 갱신이 실패해도 저장된 Profile을 실패로 뒤집지 않는다."""
    _stub_recalculation(monkeypatch, users=["user-1"])

    async def failing_sync(connection: object, **_: object) -> list[str]:
        """수집 대상 갱신 실패를 재현한다."""
        raise RuntimeError("수집 대상 갱신 실패")

    monkeypatch.setattr(
        wiki_scheduler, "sync_wiki_interest_collection_targets", failing_sync
    )

    results = asyncio.run(sch_010(object()))  # type: ignore[arg-type]

    assert results[0].status == "completed"
    assert results[0].subscribed_targets == ()


def test_sch_010_returns_empty_when_no_stale_user(monkeypatch: MonkeyPatch) -> None:
    """재계산할 사용자가 없으면 아무 것도 실행하지 않는다."""
    calls = _stub_recalculation(monkeypatch, users=[])

    results = asyncio.run(sch_010(object()))  # type: ignore[arg-type]

    assert results == []
    assert calls["int_011"] == []
