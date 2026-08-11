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


def _repository(
    connection: object,
    *,
    wiki_build_quiet_minutes: int = 0,
    wiki_build_max_wait_minutes: int = 30,
    wiki_read_pipeline_version: str = "legacy_v1",
    wiki_maintenance_pipeline_version: str = "legacy_v1",
) -> PostgresAgentJobRepository:
    """실제 DB Pool 생성 없이 피드백·조용 시간 메서드만 시험할 저장소를 만든다."""
    repository = PostgresAgentJobRepository.__new__(PostgresAgentJobRepository)
    repository._pool = _Pool(connection)  # type: ignore[assignment]
    repository._wiki_build_quiet_minutes = wiki_build_quiet_minutes
    repository._wiki_build_max_wait_minutes = wiki_build_max_wait_minutes
    repository._wiki_read_pipeline_version = wiki_read_pipeline_version
    repository._wiki_maintenance_pipeline_version = wiki_maintenance_pipeline_version
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


class _TransactionalConnection:
    """transaction() async context manager만 지원하는 Connection 대역."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """실제 커넥션처럼 Transaction 컨텍스트를 제공한다."""
        yield None


def test_repository_defaults_quiet_window_to_immediate() -> None:
    """생성자 인자를 생략하면 즉시 반영(0분) 기본값을 그대로 쓴다.

    데모·개발 환경 기본값이다. 저장이 몰리는 운영 환경은
    WIKI_BUILD_QUIET_MINUTES로 늘려 여러 건을 한 Build로 묶는다.
    """
    repository = PostgresAgentJobRepository("postgresql://fake")

    assert repository._wiki_build_quiet_minutes == 0
    assert repository._wiki_build_max_wait_minutes == 30
    assert repository._wiki_read_pipeline_version == "legacy_v1"
    assert repository._wiki_maintenance_pipeline_version == "legacy_v1"


def test_repository_stores_configured_quiet_window() -> None:
    """생성자에 넘긴 조용 시간·최대 대기시간을 그대로 보관한다."""
    repository = PostgresAgentJobRepository(
        "postgresql://fake",
        wiki_build_quiet_minutes=5,
        wiki_build_max_wait_minutes=20,
        wiki_read_pipeline_version="langgraph_v2",
        wiki_maintenance_pipeline_version="langgraph_v2",
    )

    assert repository._wiki_build_quiet_minutes == 5
    assert repository._wiki_build_max_wait_minutes == 20
    assert repository._wiki_read_pipeline_version == "langgraph_v2"
    assert repository._wiki_maintenance_pipeline_version == "langgraph_v2"


def test_submit_web_clipping_forwards_configured_quiet_window(
    monkeypatch: Any,
) -> None:
    """클리핑 저장이 저장소에 설정된 조용 시간을 db_002에 그대로 전달하는지 검증한다."""
    captured: dict[str, Any] = {}

    async def fake_db_002(_connection: object, **kwargs: Any) -> Any:
        """전달받은 인자를 기록하고 최소 Submission 결과를 돌려준다."""
        captured.update(kwargs)

        class _Saved:
            job_id = "job-1"
            source_document_id = "doc-1"
            source_document_version_id = "version-1"

        return _Saved()

    async def fake_get_agent_job(_connection: object, *, job_id: str) -> Any:
        """저장 결과 조회를 최소 레코드로 대체한다."""
        return object()

    async def fake_scope(_connection: object, *, user_id: str) -> None:
        """RLS Scope 설정을 건너뛴다."""
        return None

    monkeypatch.setattr(postgres_agent_jobs, "db_002", fake_db_002)
    monkeypatch.setattr(postgres_agent_jobs, "get_agent_job", fake_get_agent_job)
    monkeypatch.setattr(postgres_agent_jobs, "set_personal_wiki_scope", fake_scope)
    monkeypatch.setattr(
        PostgresAgentJobRepository,
        "_to_job_record",
        lambda self, stored: stored,
    )

    repository = _repository(
        _TransactionalConnection(),
        wiki_build_quiet_minutes=7,
        wiki_build_max_wait_minutes=21,
    )

    asyncio.run(
        repository.submit_web_clipping(
            user_id="user-1",
            source_event_id="clip-1",
            source_url="https://example.com",
            title="제목",
            content="# 본문",
            author=None,
            published_at=None,
            clipped_on=None,
            description=None,
            tags=[],
            occurred_at=None,
            memo=None,
            request_id="request-1",
        )
    )

    assert captured["quiet_minutes"] == 7
    assert captured["max_wait_minutes"] == 21
