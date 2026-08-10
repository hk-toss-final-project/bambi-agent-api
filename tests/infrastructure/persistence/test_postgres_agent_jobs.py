"""PostgreSQL Agent Job 저장소의 피드백 후처리 경계를 검증한다."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from infrastructure.persistence import postgres_agent_jobs
from infrastructure.persistence.postgres_agent_jobs import PostgresAgentJobRepository


class _Pool:
    """고정 Connection을 빌려주는 비동기 Pool 대역."""

    def __init__(self, connection: object) -> None:
        """테스트가 사용할 Connection 객체를 보관한다."""
        self._connection = connection

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[object]:
        """고정 Connection을 비동기 문맥으로 반환한다."""
        yield self._connection


def _repository(connection: object) -> PostgresAgentJobRepository:
    """실제 DB Pool 생성 없이 피드백 메서드만 시험할 저장소를 만든다."""
    repository = PostgresAgentJobRepository.__new__(PostgresAgentJobRepository)
    repository._pool = _Pool(connection)  # type: ignore[assignment]
    return repository


def test_feedback_recalculates_profile_after_event_commit(monkeypatch: Any) -> None:
    """신규 피드백 저장 뒤 같은 요청에서 관심 Profile을 재계산한다."""
    connection = object()
    calls: list[str] = []

    async def fake_save(*args: Any, **kwargs: Any) -> int:
        """피드백 이벤트 저장 완료를 기록한다."""
        assert args[0] is connection
        calls.append("save")
        return 1

    class _ProfileRepository:
        """재계산에 전달되는 Connection 어댑터 대역."""

        def __init__(self, current_connection: object) -> None:
            """전달받은 Connection을 검증한다."""
            assert current_connection is connection

    async def fake_recalculate(repository: object, user_id: str) -> dict[str, object]:
        """관심사 재계산 호출 순서와 사용자를 기록한다."""
        assert isinstance(repository, _ProfileRepository)
        assert user_id == "user-1"
        calls.append("recalculate")
        return {"status": "active"}

    monkeypatch.setattr(postgres_agent_jobs, "save_feedback_signals_for_user", fake_save)
    monkeypatch.setattr(
        postgres_agent_jobs, "ConnectionInterestProfileRepository", _ProfileRepository
    )
    monkeypatch.setattr(postgres_agent_jobs, "int_011", fake_recalculate)

    accepted = asyncio.run(
        _repository(connection).submit_feedback_signals(
            user_id="user-1",
            signals=[{"source_event_id": "signal-1"}],
        )
    )

    assert accepted == 1
    assert calls == ["save", "recalculate"]


def test_feedback_event_survives_recalculation_failure(monkeypatch: Any) -> None:
    """재계산 오류를 호출자에게 전파하지 않고 저장된 이벤트 수를 반환한다."""

    async def fake_save(*args: Any, **kwargs: Any) -> int:
        """이미 확정된 신규 피드백 수를 반환한다."""
        return 2

    async def fail_recalculate(*args: Any, **kwargs: Any) -> dict[str, object]:
        """Profile 재계산 실패를 재현한다."""
        raise RuntimeError("recalculation failed")

    monkeypatch.setattr(postgres_agent_jobs, "save_feedback_signals_for_user", fake_save)
    monkeypatch.setattr(postgres_agent_jobs, "int_011", fail_recalculate)

    accepted = asyncio.run(
        _repository(object()).submit_feedback_signals(
            user_id="user-1",
            signals=[{"source_event_id": "signal-1"}],
        )
    )

    assert accepted == 2


def test_duplicate_feedback_skips_recalculation(monkeypatch: Any) -> None:
    """신규 이벤트가 없으면 불필요한 Profile Version 생성을 건너뛴다."""
    recalculated = False

    async def fake_save(*args: Any, **kwargs: Any) -> int:
        """모든 이벤트가 중복인 저장 결과를 반환한다."""
        return 0

    async def fake_recalculate(*args: Any, **kwargs: Any) -> dict[str, object]:
        """호출 여부를 기록하는 재계산 대역이다."""
        nonlocal recalculated
        recalculated = True
        return {}

    monkeypatch.setattr(postgres_agent_jobs, "save_feedback_signals_for_user", fake_save)
    monkeypatch.setattr(postgres_agent_jobs, "int_011", fake_recalculate)

    accepted = asyncio.run(
        _repository(object()).submit_feedback_signals(
            user_id="user-1",
            signals=[{"source_event_id": "signal-1"}],
        )
    )

    assert accepted == 0
    assert not recalculated
