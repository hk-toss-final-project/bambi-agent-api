"""토픽 성격 판정(개인 Wiki 노드 종류 기반)과 수집 창 연동을 검증한다.

DB 없이 동작해야 하므로 판정 실패 경로가 핵심이다 — 판정이 안 되면 기존
동작(news)을 그대로 유지해야 수집이 막히지 않는다.
"""

import pytest

from agent.assistant.features import config
from agent.assistant.features.topic_intent import (
    INTENT_EVERGREEN,
    INTENT_NEWS,
    resolve_topic_intent,
    topic_document_key,
)


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


def test_resolve_intent_without_database_falls_back_to_news(monkeypatch) -> None:
    """DB 연결이 없으면 뉴스형으로 폴백해 기존 동작을 유지한다."""
    monkeypatch.delenv("AGENT_DATABASE_URL", raising=False)

    assert resolve_topic_intent("DDD", "user-1") == INTENT_NEWS


def test_resolve_intent_without_user_falls_back_to_news(monkeypatch) -> None:
    """사용자 식별자가 없으면 개인 Wiki를 조회할 수 없으므로 뉴스형으로 본다."""
    monkeypatch.setenv("AGENT_DATABASE_URL", "postgresql://unused/db")

    assert resolve_topic_intent("DDD", "") == INTENT_NEWS


def test_resolve_intent_survives_query_failure(monkeypatch) -> None:
    """조회가 실패해도 예외를 올리지 않고 뉴스형으로 폴백한다.

    성격 판정은 부가 정보이므로, 실패가 수집 자체를 막으면 안 된다.
    """
    # 연결할 수 없는 DSN을 줘서 실제 실패 경로를 태운다.
    monkeypatch.setenv("AGENT_DATABASE_URL", "postgresql://127.0.0.1:1/none")

    assert resolve_topic_intent("DDD", "user-1") == INTENT_NEWS


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
