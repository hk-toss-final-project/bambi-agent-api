"""아침 브리핑 주제 선정 규칙을 검증한다.

선정자는 사용자가 검토하지 않고 받는 경로에 쓰이므로, 없는 주제를 지어내거나
선정 실패로 브리핑을 막는 일이 없어야 한다. LLM은 실제로 부르지 않고 대체한다.
"""

import pytest

from agent.report_builder.features import briefing_topics
from agent.report_builder.features.briefing_topics import (
    InterestCandidate,
    InterestContext,
    select_briefing_topics,
)


def _context(*nodes: str, summary: str = "") -> InterestContext:
    """맥락 문장이 붙은 후보 묶음을 만든다."""
    return InterestContext(
        candidates=[InterestCandidate(node=node, context=f"{node} 설명") for node in nodes],
        user_summary=summary,
    )


def _answer(monkeypatch: pytest.MonkeyPatch, payload: str) -> list[str]:
    """선정자 응답을 고정하고 전달된 프롬프트를 기록한다."""
    prompts: list[str] = []

    def _fake(_system: str, user: str, **_kwargs: object) -> str:
        prompts.append(user)
        return payload

    monkeypatch.setattr(briefing_topics, "complete", _fake)
    return prompts


def test_selection_keeps_candidate_order_from_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """모델이 고른 순서를 그대로 쓴다 — 그 순서가 브리핑 섹션 순서다."""
    _answer(monkeypatch, '{"topics": ["환율", "프로야구", "반도체"], "reason": "최근 관심"}')

    selection = select_briefing_topics(_context("반도체", "프로야구", "환율", "DDD"))

    assert selection.topics == ("환율", "프로야구", "반도체")
    assert selection.reason == "최근 관심"


def test_selection_drops_topics_that_are_not_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """후보에 없는 이름은 버린다.

    이 값이 그대로 검색어가 되므로, 지어낸 주제를 통과시키면 자료를 한 건도 못
    찾고 섹션이 빈다.
    """
    _answer(monkeypatch, '{"topics": ["반도체", "메타버스", "환율"], "reason": ""}')

    selection = select_briefing_topics(_context("반도체", "프로야구", "환율", "DDD"))

    assert selection.topics == ("반도체", "환율")


def test_selection_restores_the_candidate_spelling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """띄어쓰기·대소문자만 다른 표기는 후보 쪽 표기로 되돌린다.

    모델이 표기를 바꿔 쓰는 일이 흔한데, 그것 때문에 멀쩡한 선택을 버릴 이유는 없다.
    검색어는 후보 표기 그대로여야 창고에 걸린다.
    """
    _answer(monkeypatch, '{"topics": ["dbeaver  community", "인덱스 튜닝"], "reason": ""}')

    selection = select_briefing_topics(
        _context("DBeaver Community", "인덱스 튜닝", "PostgreSQL", "환율"),
    )

    assert selection.topics == ("DBeaver Community", "인덱스 튜닝")


def test_selection_respects_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """요청한 개수를 넘겨 고르지 않는다."""
    _answer(monkeypatch, '{"topics": ["반도체", "환율", "프로야구", "DDD"], "reason": ""}')

    selection = select_briefing_topics(
        _context("반도체", "프로야구", "환율", "DDD"), limit=2
    )

    assert selection.topics == ("반도체", "환율")


def test_selection_removes_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    """같은 주제를 두 번 고르면 한 번만 남긴다."""
    _answer(monkeypatch, '{"topics": ["반도체", "반도체", "환율"], "reason": ""}')

    selection = select_briefing_topics(_context("반도체", "프로야구", "환율", "DDD"))

    assert selection.topics == ("반도체", "환율")


def test_selection_skips_the_model_when_candidates_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """후보가 고를 개수 이하면 물어보지 않는다.

    고를 것이 없는데 호출하면 비용과 지연만 늘어난다.
    """

    def _unexpected(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("후보가 개수 이하면 모델을 부르면 안 된다")

    monkeypatch.setattr(briefing_topics, "complete", _unexpected)

    selection = select_briefing_topics(_context("반도체", "환율"))

    assert selection.topics == ("반도체", "환율")


def test_selection_returns_empty_without_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """후보가 없으면 호출 없이 빈 결과를 돌려준다."""

    def _unexpected(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("후보가 없으면 모델을 부르면 안 된다")

    monkeypatch.setattr(briefing_topics, "complete", _unexpected)

    assert select_briefing_topics(InterestContext()).topics == ()


def test_selection_survives_model_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """호출이 실패해도 예외를 올리지 않는다.

    선정이 안 됐다고 아침 브리핑을 통째로 거르는 것보다, 빈 결과를 주고 호출자가
    기존 순서로 폴백하는 편이 낫다.
    """

    def _boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("모델 호출 실패")

    monkeypatch.setattr(briefing_topics, "complete", _boom)

    assert select_briefing_topics(_context("반도체", "환율", "DDD", "프로야구")).topics == ()


def test_selection_survives_broken_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """깨진 응답도 빈 결과로 흘려보낸다."""
    _answer(monkeypatch, "이건 JSON이 아니다")

    assert select_briefing_topics(_context("반도체", "환율", "DDD", "프로야구")).topics == ()


def test_prompt_carries_context_sentences_and_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """맥락 문장과 사용자 요약을 프롬프트에 함께 넣는다.

    이름만으로는 도구·출처를 가릴 수 없다. 선정이 가능한 이유가 이 문장들이다.
    """
    prompts = _answer(monkeypatch, '{"topics": ["반도체"], "reason": ""}')

    select_briefing_topics(
        InterestContext(
            candidates=[
                InterestCandidate(
                    node="DBeaver Community",
                    context="저장된 글 2개 모두 PostgreSQL 튜닝을 다루며 작업 수단으로만 등장한다.",
                ),
                InterestCandidate(node="반도체", context="시황 기사를 꾸준히 저장했다."),
                InterestCandidate(node="환율", context="최근 저장 없음."),
                InterestCandidate(node="DDD", context="설계 원칙 글 1건."),
            ],
            user_summary="반도체 시황을 꾸준히 따라간다.",
        ),
        limit=1,
    )

    prompt = prompts[0]
    assert "반도체 시황을 꾸준히 따라간다." in prompt
    assert "작업 수단으로만 등장한다" in prompt
    assert "고를 주제 수: 1개" in prompt
