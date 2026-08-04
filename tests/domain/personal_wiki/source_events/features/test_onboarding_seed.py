"""WSE-014 온보딩 관심사 시드 문서 합성을 검증한다.

LLM 없이 결정론으로 씨앗 Markdown을 만들고, 같은 선택이면 같은 멱등 키를,
바뀐 선택이면 다른 키를 만드는지 확인한다.
"""

import asyncio

from domain.personal_wiki.source_events.api import OnboardingSeedDocument, wse_014


def _run(**kwargs) -> OnboardingSeedDocument | None:
    """비동기 wse_014를 동기 테스트에서 실행한다."""
    return asyncio.run(wse_014(**kwargs))


def test_wse_014_synthesizes_seed_from_category_and_topics() -> None:
    """Category와 세부 Topic이 씨앗 본문·라벨에 모두 반영되는지 검증한다."""
    seed = _run(
        signup_interests=[{"category": "인공지능", "topics": ["LLM", "에이전트"]}],
        interest_taxonomy_version="v1",
        selected_category_ids=["cat-ai"],
        selected_topic_ids=["topic-llm", "topic-agent"],
    )

    assert seed is not None
    assert seed.source_event_id.startswith("onboarding-seed:")
    assert "## 인공지능" in seed.content
    assert "LLM" in seed.content and "에이전트" in seed.content
    assert seed.topics == ("LLM", "에이전트")
    assert seed.metadata["interest_taxonomy_version"] == "v1"
    assert seed.metadata["selected_category_ids"] == ["cat-ai"]


def test_wse_014_uses_category_when_no_topics() -> None:
    """세부 Topic 없이 Category만 골라도 씨앗이 만들어지는지 검증한다."""
    seed = _run(signup_interests=[{"category": "우주", "topics": []}])

    assert seed is not None
    assert "## 우주" in seed.content
    assert seed.topics == ("우주",)


def test_wse_014_returns_none_for_empty_selection() -> None:
    """유효한 선택이 없으면 None을 반환하는지 검증한다."""
    assert _run(signup_interests=[]) is None
    assert _run(signup_interests=[{"category": "", "topics": []}]) is None


def test_wse_014_is_idempotent_for_same_selection() -> None:
    """같은 선택은 같은 멱등 키, 바뀐 선택은 다른 키를 만드는지 검증한다."""
    first = _run(
        signup_interests=[{"category": "경제", "topics": ["금리"]}],
        interest_taxonomy_version="v1",
    )
    same = _run(
        signup_interests=[{"category": "경제", "topics": ["금리"]}],
        interest_taxonomy_version="v1",
    )
    changed = _run(
        signup_interests=[{"category": "경제", "topics": ["환율"]}],
        interest_taxonomy_version="v1",
    )

    assert first is not None and same is not None and changed is not None
    assert first.source_event_id == same.source_event_id
    assert first.source_event_id != changed.source_event_id


def test_wse_014_handles_mixed_korean_english_and_multiple_groups() -> None:
    """한/영 혼용과 다중 관심 묶음을 모두 씨앗에 담는지 검증한다."""
    seed = _run(
        signup_interests=[
            {"category": "Tech", "topics": ["반도체", "AI chip"]},
            {"category": "문화", "topics": ["K-pop"]},
        ],
    )

    assert seed is not None
    assert "## Tech" in seed.content and "## 문화" in seed.content
    assert set(seed.topics) == {"반도체", "AI chip", "K-pop"}
