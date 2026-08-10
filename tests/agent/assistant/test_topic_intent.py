"""토픽 성격 판정(주제 자체를 LLM에 묻는다)과 수집 창 연동을 검증한다.

판정 실패 경로가 핵심이다 — 실패하면 news로 폴백해야 오래된 자료를 최신 소식처럼
쓰는 사고가 안 난다. LLM은 실제로 부르지 않고 대체한다.
"""

import pytest

from agent.assistant.features import config, topic_intent
from agent.assistant.features.topic_intent import (
    INTENT_EVERGREEN,
    INTENT_NEWS,
    clear_topic_intent_cache,
    resolve_topic_intent,
    topic_document_key,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """판정 캐시가 케이스 사이에 새지 않게 한다."""
    clear_topic_intent_cache()
    yield
    clear_topic_intent_cache()


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("ADR 상장", "adr-상장"),
        # 괄호·기호도 하이픈으로 접힌다(실제 Wiki 저장 형식과 일치해야 조회된다).
        ("DDD(Domain-Driven Design)", "ddd-domain-driven-design"),
        ("DTO(Data Transfer Object)", "dto-data-transfer-object"),
        ("  서킷 브레이커  ", "서킷-브레이커"),
        ("Application Layer", "application-layer"),
        ("", ""),
    ],
)
def test_topic_document_key_normalizes_to_wiki_format(topic: str, expected: str) -> None:
    """토픽을 Wiki document_key 형식(소문자·하이픈)으로 정규화한다."""
    assert topic_document_key(topic) == expected


def test_resolve_intent_reads_the_model_answer(monkeypatch) -> None:
    """모델이 evergreen이라고 답하면 개념형으로 판정한다."""
    monkeypatch.setattr(topic_intent, "complete", lambda *_a, **_k: "evergreen")

    assert resolve_topic_intent("인덱스 튜닝") == INTENT_EVERGREEN


def test_resolve_intent_judges_the_topic_not_the_wiki_node_kind(monkeypatch) -> None:
    """개념처럼 생긴 주제라도 시의성이 있으면 뉴스형으로 판정한다.

    2026-08-10 실측: '로또'가 Wiki에 concept으로 저장돼 evergreen(90일)이 되는
    바람에, 아침 브리핑이 일주일 전 1235회 기사로 "다음 추첨은 8월 8일 예정"이라고
    썼다(그날은 8월 10일). 노드 종류가 아니라 주제 자체를 봐야 한다.
    """
    monkeypatch.setattr(topic_intent, "complete", lambda *_a, **_k: "news")

    assert resolve_topic_intent("로또") == INTENT_NEWS


def test_resolve_intent_asks_the_model_once_per_topic(monkeypatch) -> None:
    """같은 주제는 한 번만 묻는다.

    아침 브리핑은 매일 같은 주제로 돌고, 여러 주제를 묶는 리포트는 한 번에 여러 번
    부른다. 매번 물으면 호출이 그만큼 늘어난다.
    """
    calls: list[str] = []

    def _fake(_system: str, user: str, **_k: object) -> str:
        calls.append(user)
        return "evergreen"

    monkeypatch.setattr(topic_intent, "complete", _fake)

    assert resolve_topic_intent("제텔카스텐") == INTENT_EVERGREEN
    assert resolve_topic_intent("  제텔카스텐  ") == INTENT_EVERGREEN
    assert len(calls) == 1


def test_resolve_intent_survives_model_failure(monkeypatch) -> None:
    """호출이 실패해도 예외를 올리지 않고 뉴스형으로 폴백한다.

    오래된 자료를 최신 소식처럼 쓰는 실수가 최신 자료만 쓰는 실수보다 나쁘다.
    """

    def _boom(*_a: object, **_k: object) -> str:
        raise RuntimeError("모델 호출 실패")

    monkeypatch.setattr(topic_intent, "complete", _boom)

    assert resolve_topic_intent("DDD") == INTENT_NEWS


def test_resolve_intent_treats_unknown_answers_as_news(monkeypatch) -> None:
    """모르는 응답은 뉴스형으로 둔다."""
    monkeypatch.setattr(topic_intent, "complete", lambda *_a, **_k: "아마도 개념형")

    assert resolve_topic_intent("DDD") == INTENT_NEWS


def test_resolve_intent_without_topic_does_not_call_the_model(monkeypatch) -> None:
    """빈 주제는 묻지 않고 뉴스형으로 둔다."""

    def _unexpected(*_a: object, **_k: object) -> str:
        raise AssertionError("빈 주제로 모델을 부르면 안 된다")

    monkeypatch.setattr(topic_intent, "complete", _unexpected)

    assert resolve_topic_intent("   ") == INTENT_NEWS


def test_collect_window_widens_for_evergreen_topics() -> None:
    """개념형 토픽의 수집 창이 뉴스형보다 넓어야 한다.

    같은 창(3일)을 쓰면 개념형 토픽만 선택적으로 0건이 된다
    (2026-07-27 'DDD' 리포트 실측: 수집 14건 중 9건 outside_window 탈락).
    """
    news_hours = config.collect_window_hours(INTENT_NEWS)
    evergreen_hours = config.collect_window_hours(INTENT_EVERGREEN)

    assert news_hours == config.COLLECT_WINDOW_DAYS * 24.0
    assert evergreen_hours == config.EVERGREEN_WINDOW_DAYS * 24.0
    # 개념 글은 몇 주 전 자료가 정상이므로 최소 한 달 이상은 봐야 한다.
    assert evergreen_hours >= 30 * 24.0
    assert evergreen_hours > news_hours


def test_collect_window_defaults_to_news() -> None:
    """성격을 지정하지 않으면 뉴스형 창을 쓴다(기존 호출 호환)."""
    assert config.collect_window_hours() == config.collect_window_hours(INTENT_NEWS)
