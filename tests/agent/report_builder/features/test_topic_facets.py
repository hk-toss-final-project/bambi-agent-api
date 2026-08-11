"""주제별 보조 검색어 생성 규칙을 검증한다.

검색어 생성이 실패해도 수집이 멈추면 안 되고, 같은 검색을 두 번 하게 만들어서도
안 된다. LLM은 실제로 부르지 않고 대체한다.
"""

import pytest

from agent.report_builder.features import topic_facets
from agent.report_builder.features.topic_facets import generate_topic_facets


def _answer(monkeypatch: pytest.MonkeyPatch, payload: str) -> list[str]:
    """생성기 응답을 고정하고 전달된 프롬프트를 기록한다."""
    prompts: list[str] = []

    def _fake(_system: str, user: str, **_kwargs: object) -> str:
        prompts.append(user)
        return payload

    monkeypatch.setattr(topic_facets, "complete", _fake)
    return prompts


def test_returns_generated_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    """만들어진 보조 검색어를 순서대로 돌려준다."""
    _answer(
        monkeypatch,
        '{"queries": ["다낭 가볼 만한 곳", "다낭 날씨", "다낭 맛집"]}',
    )

    assert generate_topic_facets("다낭 여행", intent="evergreen") == (
        "다낭 가볼 만한 곳",
        "다낭 날씨",
        "다낭 맛집",
    )


def test_drops_queries_that_repeat_the_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    """원 주제와 같은 뜻인 검색어는 버린다.

    같은 검색을 두 번 하면 외부 호출만 늘고 결과는 그대로다. 공백·대소문자만
    다른 것도 같은 검색으로 본다.
    """
    _answer(monkeypatch, '{"queries": ["다낭  여행", "다낭 날씨"]}')

    assert generate_topic_facets("다낭 여행") == ("다낭 날씨",)


def test_removes_duplicates_among_generated_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """생성된 검색어끼리 겹쳐도 한 번만 남긴다."""
    _answer(monkeypatch, '{"queries": ["다낭 날씨", "다낭날씨", "다낭 맛집"]}')

    assert generate_topic_facets("다낭 여행") == ("다낭 날씨", "다낭 맛집")


def test_respects_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """요청한 개수를 넘겨 돌려주지 않는다.

    검색어마다 소스를 다 도므로 개수가 곧 외부 호출 수와 시간이다.
    """
    _answer(monkeypatch, '{"queries": ["A", "B", "C", "D"]}')

    assert generate_topic_facets("다낭 여행", limit=2) == ("A", "B")


def test_returns_empty_when_the_model_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """호출이 실패하면 빈 결과를 준다.

    검색어를 못 만들었다고 수집을 막을 이유는 없다 — 호출자가 주제어 하나로
    기존과 똑같이 수집한다.
    """

    def _boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("모델 호출 실패")

    monkeypatch.setattr(topic_facets, "complete", _boom)

    assert generate_topic_facets("다낭 여행") == ()


def test_returns_empty_on_broken_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """깨진 응답도 빈 결과로 흘려보낸다."""
    _answer(monkeypatch, "이건 JSON이 아니다")

    assert generate_topic_facets("다낭 여행") == ()


def test_skips_the_call_without_a_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    """주제가 비었거나 개수가 0이면 부르지 않는다."""

    def _unexpected(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("부를 이유가 없다")

    monkeypatch.setattr(topic_facets, "complete", _unexpected)

    assert generate_topic_facets("   ") == ()
    assert generate_topic_facets("다낭 여행", limit=0) == ()


def test_prompt_carries_the_topic_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    """주제 성격을 프롬프트에 넣는다.

    뉴스형은 "무엇이 달라졌나", 개념형은 "무엇을 알아야 하나"를 물어야 해서
    이 값이 결과를 가른다.
    """
    prompts = _answer(monkeypatch, '{"queries": ["다낭 날씨"]}')

    generate_topic_facets("다낭 여행", intent="evergreen", limit=1)

    assert "주제: 다낭 여행" in prompts[0]
    assert "intent: evergreen" in prompts[0]
    assert "1개" in prompts[0]


def test_prompt_carries_the_topic_description(monkeypatch: pytest.MonkeyPatch) -> None:
    """주제 설명이 있으면 프롬프트에 함께 넣는다.

    이름만으로는 무엇에 관한 주제인지 모른다(2026-08-11 실측: `코리`에 "최신
    뉴스"·"활동 소식" 같은 아무 데나 붙는 검색어가 생성됐다).
    """
    prompts = _answer(monkeypatch, '{"queries": ["코리 제약 파이프라인"]}')

    generate_topic_facets(
        "코리", context="북경 한미약품과 협력하는 제약 기업", limit=1
    )

    assert "주제 설명: 북경 한미약품과 협력하는 제약 기업" in prompts[0]


def test_prompt_omits_the_description_line_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """설명이 없으면 그 줄을 아예 넣지 않는다."""
    prompts = _answer(monkeypatch, '{"queries": ["다낭 날씨"]}')

    generate_topic_facets("다낭 여행", limit=1)

    assert "주제 설명" not in prompts[0]
