"""아침 브리핑 주제 선정 서비스를 검증한다.

Repository와 선정자를 대체해 LLM·DB 없이 조립 경로만 확인한다.
"""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from agent.report_builder.api import (
    BriefingTopicSelection,
    CandidateMaterial,
    CandidateSource,
    InterestContext,
)
from app.services import briefing_topics as service_module
from app.services.briefing_topics import BriefingTopicsService


class _FakeRepository:
    """고정 후보 원자재를 돌려주고 요청받은 후보 수를 기록한다."""

    def __init__(self, materials: Sequence[CandidateMaterial]) -> None:
        """반환할 원자재를 보관한다."""
        self._materials = materials
        self.requested_limit: int | None = None

    async def load_briefing_candidates(
        self, user_id: str, *, limit: int
    ) -> Sequence[CandidateMaterial]:
        """요청 후보 수를 기록하고 준비된 원자재를 반환한다."""
        assert user_id == "user-1"
        self.requested_limit = limit
        return self._materials


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

    response = asyncio.run(BriefingTopicsService(repository).get_topics("user-1"))

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
        BriefingTopicsService(_FakeRepository(_materials())).get_topics("user-1")
    )

    contexts = {candidate.node: candidate.context for candidate in seen[0].candidates}
    assert "PostgreSQL 인덱스 튜닝" in contexts["DBeaver Community"]
    assert "마지막 저장" in contexts["삼성전자"]


def test_service_returns_empty_topics_for_a_user_without_wiki() -> None:
    """위키가 없으면 빈 목록을 정상 응답으로 돌려준다.

    계약상 Service는 topics가 비면 아침 요청을 보내지 않고 등록 관심사 폴백으로
    넘어간다. 여기서 오류를 내면 그 폴백이 안 돈다. 후보가 없으면 선정자가
    LLM을 부르지 않으므로 실제 선정자를 그대로 쓴다.
    """
    response = asyncio.run(
        BriefingTopicsService(_FakeRepository([])).get_topics("user-1")
    )

    assert response.topics == []
    assert response.candidate_count == 0
