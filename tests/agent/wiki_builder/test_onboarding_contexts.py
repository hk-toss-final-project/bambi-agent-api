"""온보딩 Topic 컨텍스트 해석 우선순위와 폴백을 검증한다."""

import json

from agent.wiki_builder.features.classification import (
    classify_onboarding_seed_for_wiki,
)
from agent.wiki_builder.features.onboarding_contexts import (
    CUSTOM_TOPIC_PROMPT_VERSION,
    resolve_onboarding_contexts,
)
from shared.onboarding_context_models import (
    OnboardingTopicContext,
    topic_context_signature,
)
from shared.wiki_models import ExistingWikiEntry


def _official(
    topic_id: str = "ai_ml", name: str = "AI·머신러닝"
) -> OnboardingTopicContext:
    """테스트용 정식 Topic 컨텍스트를 만든다."""
    return OnboardingTopicContext(
        original_keyword=name,
        canonical_name=name,
        node_kind="concept",
        subtype="field",
        definition="데이터에서 패턴을 학습하는 인공지능 분야다.",
        key_characteristics=("모델 학습", "추론"),
        applications=("업무 자동화",),
        aliases=("인공지능", "AI"),
        taxonomy_version="1.0.0-draft",
        topic_id=topic_id,
    )


def test_official_topic_uses_seeded_context_without_llm() -> None:
    """선택 ID가 있는 정식 Topic은 DB 컨텍스트만으로 해석·분류한다."""

    def fail_generator(*_args, **_kwargs) -> str:
        raise AssertionError("정식 Topic에서 LLM을 호출하면 안 됩니다.")

    result = resolve_onboarding_contexts(
        selected_topic_ids=["ai_ml"],
        custom_keywords=[],
        taxonomy_version="1.0.0-draft",
        locale="ko",
        taxonomy_contexts=[_official()],
        cached_contexts=[],
        existing_entries=[],
        generator=fail_generator,
    )
    classification = classify_onboarding_seed_for_wiki(
        {"labels": ["AI·머신러닝"]},
        resolved_contexts=result.contexts,
    )

    assert result.generated_contexts == ()
    assert [concept.title for concept in classification.concepts] == ["AI·머신러닝"]
    concept = classification.concepts[0]
    assert concept.definition.startswith("데이터에서")
    assert concept.key_characteristics == ["모델 학습", "추론"]
    assert concept.context_metadata["onboarding_context"]["topic_id"] == "ai_ml"


def test_custom_keyword_prefers_taxonomy_alias_then_existing_wiki() -> None:
    """추가 키워드는 정식 별칭과 기존 Wiki exact match를 LLM보다 먼저 쓴다."""
    existing = ExistingWikiEntry(
        document_kind="entity",
        document_key="openai",
        title="OpenAI",
        domain="organization",
        summary="AI 연구와 제품을 만드는 조직이다.",
        metadata={"aliases": ["오픈AI"]},
    )

    def fail_generator(*_args, **_kwargs) -> str:
        raise AssertionError("exact match에서 LLM을 호출하면 안 됩니다.")

    result = resolve_onboarding_contexts(
        selected_topic_ids=[],
        custom_keywords=["AI", "오픈AI"],
        taxonomy_version="1.0.0-draft",
        locale="ko",
        taxonomy_contexts=[_official()],
        cached_contexts=[],
        existing_entries=[existing],
        generator=fail_generator,
    )

    assert [context.resolution_kind for context in result.contexts] == [
        "taxonomy_alias",
        "existing_wiki",
    ]
    assert result.contexts[1].matched_existing_key == "openai"


def test_matching_cache_avoids_llm() -> None:
    """Prompt·taxonomy 서명이 같은 사용자 캐시는 그대로 재사용한다."""
    signature = topic_context_signature(
        keyword="양자 센서",
        taxonomy_version="1.0.0-draft",
        locale="ko",
        prompt_version=CUSTOM_TOPIC_PROMPT_VERSION,
    )
    cached = OnboardingTopicContext(
        original_keyword="양자 센서",
        canonical_name="양자 센서",
        node_kind="concept",
        subtype="field",
        definition="양자 효과를 이용해 물리량을 정밀 측정하는 센서 분야다.",
        locale="ko",
        resolution_kind="llm_generated",
        context_signature=signature,
    )

    def fail_generator(*_args, **_kwargs) -> str:
        raise AssertionError("유효 캐시에서 LLM을 호출하면 안 됩니다.")

    result = resolve_onboarding_contexts(
        selected_topic_ids=[],
        custom_keywords=["양자 센서"],
        taxonomy_version="1.0.0-draft",
        locale="ko",
        taxonomy_contexts=[],
        cached_contexts=[cached],
        existing_entries=[],
        generator=fail_generator,
    )

    assert result.contexts == (cached,)
    assert result.generated_contexts == ()


def test_missing_custom_keywords_use_one_batched_llm_call() -> None:
    """여러 cache miss는 한 LLM 요청으로 일반론 컨텍스트를 생성한다."""
    calls: list[dict[str, object]] = []

    def generate(_system: str, user: str, *, model: str) -> str:
        calls.append({"payload": json.loads(user), "model": model})
        return json.dumps(
            {
                "topics": [
                    {
                        "keyword": "양자 센서",
                        "canonical_name": "양자 센서",
                        "node_kind": "concept",
                        "subtype": "field",
                        "definition": "양자 효과로 물리량을 측정하는 센서 분야다.",
                        "key_characteristics": ["정밀 측정"],
                        "applications": ["계측"],
                        "aliases": [],
                        "search_terms": ["quantum sensing"],
                        "possible_meanings": [],
                        "confidence": 0.9,
                    },
                    {
                        "keyword": "Project Bambi",
                        "canonical_name": "Project Bambi",
                        "node_kind": "entity",
                        "subtype": "project",
                        "definition": "사용자가 관심을 표시한 프로젝트 이름이다.",
                        "key_characteristics": [],
                        "applications": ["관련 자료 연결"],
                        "aliases": [],
                        "search_terms": ["Project Bambi"],
                        "possible_meanings": ["동명 프로젝트"],
                        "confidence": 0.6,
                    },
                ]
            },
            ensure_ascii=False,
        )

    result = resolve_onboarding_contexts(
        selected_topic_ids=[],
        custom_keywords=["양자 센서", "Project Bambi"],
        taxonomy_version="1.0.0-draft",
        locale="ko",
        taxonomy_contexts=[],
        cached_contexts=[],
        existing_entries=[],
        model="fake-model",
        generator=generate,
    )

    assert len(calls) == 1
    assert calls[0]["payload"]["keywords"] == ["양자 센서", "Project Bambi"]
    assert [context.node_kind for context in result.contexts] == ["concept", "entity"]
    assert result.generated_contexts == result.contexts
    assert all(context.context_signature for context in result.contexts)


def test_llm_failure_uses_cacheable_generic_context() -> None:
    """LLM 장애는 Build 실패가 아니라 서명된 일반론 컨텍스트로 복구한다."""

    def fail_generator(*_args, **_kwargs) -> str:
        raise RuntimeError("provider unavailable")

    result = resolve_onboarding_contexts(
        selected_topic_ids=[],
        custom_keywords=["모호한 키워드"],
        taxonomy_version="1.0.0-draft",
        locale="ko",
        taxonomy_contexts=[],
        cached_contexts=[],
        existing_entries=[],
        generator=fail_generator,
    )

    context = result.contexts[0]
    assert context.resolution_kind == "generic_fallback"
    assert context.context_signature is not None
    assert "일반적인 배경" in context.definition
    assert result.warnings
