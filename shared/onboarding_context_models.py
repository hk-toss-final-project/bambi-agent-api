"""온보딩 Topic 컨텍스트 해석과 저장 경계에서 공유하는 값 객체.

agent의 해석 로직과 infrastructure의 PostgreSQL 구현이 서로를 직접 import하지
않도록, DB·LLM에 의존하지 않는 데이터만 이 모듈에 둔다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def normalize_topic_keyword(value: str) -> str:
    """캐시·별칭 비교에 쓸 사용자 Topic 문자열을 안정적으로 정규화한다."""
    return " ".join(value.casefold().split())


def topic_context_signature(
    *, keyword: str, taxonomy_version: str | None, locale: str, prompt_version: str
) -> str:
    """taxonomy·locale·Prompt가 바뀌면 무효화되는 키워드 컨텍스트 서명."""
    material = "|".join(
        (
            normalize_topic_keyword(keyword),
            taxonomy_version or "",
            locale,
            prompt_version,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class OnboardingTopicContext:
    """정식 Topic 또는 사용자 추가 키워드에서 해석한 Wiki 컨텍스트 한 건."""

    original_keyword: str
    canonical_name: str
    node_kind: str
    subtype: str
    definition: str
    key_characteristics: tuple[str, ...] = ()
    applications: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    related_topic_ids: tuple[str, ...] = ()
    search_terms: tuple[str, ...] = ()
    possible_meanings: tuple[str, ...] = ()
    taxonomy_version: str | None = None
    topic_id: str | None = None
    locale: str = "ko-KR"
    content_version: int = 1
    resolution_kind: str = "deterministic_topic"
    confidence: float = 1.0
    context_signature: str | None = None
    matched_existing_key: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OnboardingContextResolution:
    """한 온보딩 시드의 컨텍스트 해석 결과와 새 캐시 저장 후보."""

    contexts: tuple[OnboardingTopicContext, ...]
    generated_contexts: tuple[OnboardingTopicContext, ...] = ()
    model_trace: str = "deterministic:onboarding-topic-context-v1"
    warnings: tuple[str, ...] = ()
