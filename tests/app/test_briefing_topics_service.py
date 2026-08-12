"""아침 브리핑 주제 선정 서비스를 검증한다.

Repository와 선정자를 대체해 LLM·DB 없이 조립 경로만 확인한다.
"""

import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any, Mapping

import pytest

from agent.report_builder.api import (
    BriefingTopicSelection,
    CandidateMaterial,
    CandidateSource,
    InterestContext,
)
from app.services import briefing_topics as service_module
from app.schemas.briefing_topics import BriefingPreparationRequest
from app.services.agent_jobs import AgentJobRecord
from app.services.briefing_topics import BriefingTopicsService
from infrastructure.persistence.api import (
    StoredBriefingTopicSelection,
    StoredBriefingTopicSnapshot,
)


class _FakeRepository:
    """고정 후보 원자재를 돌려주고 요청받은 후보 수를 기록한다."""

    def __init__(
        self,
        materials: Sequence[CandidateMaterial],
        snapshot: StoredBriefingTopicSnapshot | None = None,
    ) -> None:
        """반환할 원자재를 보관한다."""
        self._materials = materials
        self._snapshot = snapshot
        self.requested_limit: int | None = None

    async def load_briefing_candidates(
        self, user_id: str, *, limit: int
    ) -> Sequence[CandidateMaterial]:
        """요청 후보 수를 기록하고 준비된 원자재를 반환한다."""
        assert user_id == "user-1"
        self.requested_limit = limit
        return self._materials

    async def load_briefing_topic_snapshot(
        self, user_id: str, *, briefing_date: date
    ) -> StoredBriefingTopicSnapshot | None:
        """준비된 테스트 Snapshot을 반환한다."""
        return self._snapshot

    async def save_briefing_topic_snapshot(
        self,
        user_id: str,
        *,
        briefing_date: date,
        topics: Sequence[str],
        reason: str,
        candidate_count: int,
        contexts_by_topic: Mapping[str, Sequence[Mapping[str, object]]],
        prepared_by_job_id: str,
    ) -> StoredBriefingTopicSnapshot:
        """테스트에서 전달된 준비 결과를 Snapshot으로 보관한다."""
        self._snapshot = StoredBriefingTopicSnapshot(
            user_id=user_id,
            briefing_date=briefing_date,
            topics=tuple(topics),
            reason=reason,
            candidate_count=candidate_count,
            contexts_by_topic={
                topic: [dict(context) for context in contexts]
                for topic, contexts in contexts_by_topic.items()
            },
            prepared_by_job_id=prepared_by_job_id,
            prepared_at=datetime(2026, 8, 11, tzinfo=UTC),
        )
        return self._snapshot


class _FakeAgentJobs:
    """브리핑 준비 Job 접수 인자를 기록하는 저장소 대역."""

    def __init__(self) -> None:
        """빈 호출 기록을 초기화한다."""
        self.submitted: dict[str, Any] = {}

    async def submit_briefing_preparation(self, **kwargs: Any) -> AgentJobRecord:
        """접수 인자를 기록하고 queued Job을 반환한다."""
        self.submitted.update(kwargs)
        created_at = datetime(2026, 8, 11, tzinfo=UTC)
        return AgentJobRecord(
            job_id="job-1",
            feature_id="REPORT-022",
            job_type="briefing_preparation",
            user_id=str(kwargs["user_id"]),
            idempotency_key=str(kwargs["idempotency_key"]),
            status="queued",
            progress=0,
            request_id=str(kwargs["request_id"]),
            created_at=created_at,
            updated_at=created_at,
        )

def _materials() -> list[CandidateMaterial]:
    """도구 하나와 진짜 관심사 하나가 섞인 후보를 만든다."""
    saved = datetime(2026, 8, 8, tzinfo=UTC)
    return [
        CandidateMaterial(
            node="DBeaver Community",
            summary="오픈소스 DB 클라이언트.",
            sources=(CandidateSource(title="PostgreSQL 인덱스 튜닝", saved_at=saved),),
        ),
        CandidateMaterial(
            node="삼성전자",
            summary="반도체 기업.",
            sources=(CandidateSource(title="메모리 감산 효과", saved_at=saved),),
        ),
    ]


def _stub_selector(
    monkeypatch: pytest.MonkeyPatch, topics: tuple[str, ...]
) -> list[InterestContext]:
    """선정자를 고정 응답으로 대체하고 전달된 맥락을 기록한다."""
    seen: list[InterestContext] = []

    def _select(context: InterestContext, **_kwargs: object) -> BriefingTopicSelection:
        seen.append(context)
        return BriefingTopicSelection(topics=topics, reason="시황을 꾸준히 저장했다.")

    monkeypatch.setattr(service_module, "select_briefing_topics", _select)
    return seen


def test_service_asks_for_more_candidates_than_it_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """고를 개수보다 훨씬 많은 후보를 요청한다.

    상위 3개만 받으면 연결 수 순위가 그대로 결과가 되어, 고치려던 문제
    (실측: DBeaver 1.00 > 삼성전자)가 자르는 단계에서 그대로 남는다.
    """
    repository = _FakeRepository(_materials())
    _stub_selector(monkeypatch, ("삼성전자",))

    response = asyncio.run(BriefingTopicsService(repository).select_topics("user-1"))

    assert repository.requested_limit == 30
    assert response.topics == ["삼성전자"]
    assert response.candidate_count == 2
    assert response.reason == "시황을 꾸준히 저장했다."


def test_service_passes_assembled_context_to_the_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """출처 제목과 저장 시점이 선정자에게 전달된다.

    이름만으로는 도구와 관심사를 못 가른다. 출처 목록이 그 판단 근거다.
    """
    seen = _stub_selector(monkeypatch, ("삼성전자",))

    asyncio.run(
        BriefingTopicsService(_FakeRepository(_materials())).select_topics("user-1")
    )

    contexts = {candidate.node: candidate.context for candidate in seen[0].candidates}
    assert "PostgreSQL 인덱스 튜닝" in contexts["DBeaver Community"]
    assert "마지막 저장" in contexts["삼성전자"]


class _CachingRepository(_FakeRepository):
    """선정 결과 저장까지 지원하는 Repository 대역."""

    def __init__(
        self,
        materials: Sequence[CandidateMaterial],
        *,
        stored: StoredBriefingTopicSelection | None = None,
        stored_digest: str | None = None,
    ) -> None:
        """미리 저장돼 있다고 볼 결과와 그 지문을 보관한다."""
        super().__init__(materials)
        self._stored = stored
        self._stored_digest = stored_digest
        self.saved: dict[str, object] | None = None

    async def load_topic_selection(
        self, user_id: str, *, candidate_digest: str, topic_limit: int
    ) -> StoredBriefingTopicSelection | None:
        """지문이 저장 당시와 같을 때만 결과를 돌려준다."""
        if self._stored is None or candidate_digest != self._stored_digest:
            return None
        return self._stored

    async def save_topic_selection(
        self, user_id: str, *, candidate_digest: str, **fields: object
    ) -> None:
        """저장 호출을 기록한다."""
        self.saved = {"user_id": user_id, "digest": candidate_digest, **fields}


def test_service_reuses_the_stored_selection_without_calling_the_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """후보가 그대로면 저장된 주제를 그대로 돌려주고 LLM을 부르지 않는다.

    Service는 03:00에 주제를 미리 물어 그 주제로 창고 수집을 걸고 07:00에 같은
    엔드포인트를 다시 부른다. 두 호출이 다른 답을 주면 새벽에 모아둔 자료가
    맞지 않는다.
    """
    materials = _materials()
    repository = _CachingRepository(
        materials,
        stored=StoredBriefingTopicSelection(
            topics=("삼성전자", "폭염"), reason="03:00에 골랐다.", candidate_count=2
        ),
        stored_digest=service_module._candidate_digest(materials),
    )
    seen = _stub_selector(monkeypatch, ("전혀 다른 주제",))

    response = asyncio.run(BriefingTopicsService(repository).select_topics("user-1"))

    assert response.topics == ["삼성전자", "폭염"]
    assert response.reason == "03:00에 골랐다."
    assert seen == [], "재사용했다면 선정자를 부르면 안 된다"


def test_service_reselects_when_the_wiki_changed_overnight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """밤사이 후보가 달라지면 저장된 결과를 쓰지 않고 새로 고른다."""
    repository = _CachingRepository(
        _materials(),
        stored=StoredBriefingTopicSelection(
            topics=("옛날 주제",), reason="어제 골랐다.", candidate_count=1
        ),
        stored_digest="밤사이-바뀌기-전-지문",
    )
    _stub_selector(monkeypatch, ("삼성전자",))

    response = asyncio.run(BriefingTopicsService(repository).select_topics("user-1"))

    assert response.topics == ["삼성전자"]


def test_service_stores_the_selection_for_the_next_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """새로 고른 주제를 07:00 호출이 다시 쓸 수 있게 저장한다."""
    repository = _CachingRepository(_materials())
    _stub_selector(monkeypatch, ("삼성전자",))

    asyncio.run(BriefingTopicsService(repository).select_topics("user-1"))

    assert repository.saved is not None
    assert repository.saved["topics"] == ["삼성전자"]
    assert repository.saved["topic_limit"] == 3


def test_service_still_selects_when_the_cache_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """캐시 조회가 실패해도 주제 선정 자체는 돌아야 한다.

    캐시는 편의 장치라 여기서 예외가 새면 07:00 아침 발화가 통째로 막힌다.
    """

    class _BrokenCache(_FakeRepository):
        async def load_topic_selection(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("DB 연결 실패")

    _stub_selector(monkeypatch, ("삼성전자",))

    response = asyncio.run(
        BriefingTopicsService(_BrokenCache(_materials())).select_topics("user-1")
    )

    assert response.topics == ["삼성전자"]


def test_service_returns_empty_topics_for_a_user_without_wiki() -> None:
    """위키가 없으면 빈 목록을 정상 응답으로 돌려준다.

    계약상 Service는 topics가 비면 아침 요청을 보내지 않고 등록 관심사 폴백으로
    넘어간다. 여기서 오류를 내면 그 폴백이 안 돈다. 후보가 없으면 선정자가
    LLM을 부르지 않으므로 실제 선정자를 그대로 쓴다.
    """
    response = asyncio.run(
        BriefingTopicsService(_FakeRepository([])).select_topics("user-1")
    )

    assert response.topics == []
    assert response.candidate_count == 0


def test_get_topics_reads_prepared_snapshot_without_selecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """07시 조회는 준비 Snapshot만 읽고 선정 LLM을 다시 호출하지 않는다."""
    snapshot = StoredBriefingTopicSnapshot(
        user_id="user-1",
        briefing_date=date(2026, 8, 12),
        topics=("반도체", "프로야구"),
        reason="미리 선정함",
        candidate_count=12,
        contexts_by_topic={},
        prepared_by_job_id="job-1",
        prepared_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    monkeypatch.setattr(
        service_module,
        "select_briefing_topics",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Snapshot 조회에서 선정자를 호출하면 안 됩니다.")
        ),
    )

    response = asyncio.run(
        BriefingTopicsService(_FakeRepository([], snapshot)).get_topics(
            "user-1",
            briefing_date=date(2026, 8, 12),
        )
    )

    assert response.topics == ["반도체", "프로야구"]
    assert response.reason == "미리 선정함"


def test_get_topics_returns_empty_when_preparation_is_missing() -> None:
    """준비 Snapshot이 없으면 07시 조회가 외부 호출 없이 빈 목록을 반환한다."""
    response = asyncio.run(
        BriefingTopicsService(_FakeRepository([])).get_topics(
            "user-1",
            briefing_date=date(2026, 8, 12),
        )
    )

    assert response.topics == []
    assert response.candidate_count == 0


def test_enqueue_preparation_returns_accepted_job() -> None:
    """Service 요청 본문이 사용자·날짜별 멱등 Job 접수로 전달된다."""
    jobs = _FakeAgentJobs()
    payload = BriefingPreparationRequest(
        briefing_date=date(2026, 8, 12),
        idempotency_key="briefing:2026-08-12:user-1",
        limit=3,
    )

    response = asyncio.run(
        BriefingTopicsService(
            _FakeRepository([]),
            jobs,  # type: ignore[arg-type]
        ).enqueue_preparation("user-1", payload, request_id="request-1")
    )

    assert response.job_id == "job-1"
    assert response.status.value == "queued"
    assert jobs.submitted["briefing_date"] == date(2026, 8, 12)
