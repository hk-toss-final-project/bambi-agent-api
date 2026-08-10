"""온보딩 정식 Topic과 사용자 추가 키워드의 Wiki 컨텍스트 해석."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from agent.llm.api import complete, strip_json_fence
from shared.onboarding_context_models import (
    OnboardingContextResolution,
    OnboardingTopicContext,
    normalize_topic_keyword,
    topic_context_signature,
)
from shared.wiki_models import ExistingWikiEntry

CUSTOM_TOPIC_PROMPT_VERSION = "custom-topic-context-v1"
ONBOARDING_CONTEXT_MODEL = "deterministic:onboarding-topic-context-v1"

_PROMPT_PATH = (
    Path(__file__).parents[2] / "prompts" / "templates" / "custom_topic_context.md"
)
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()
_ENTITY_SUBTYPES = {
    "person",
    "organization",
    "project",
    "product",
    "event",
    "place",
    "other",
}
_CONCEPT_SUBTYPES = {
    "theory",
    "method",
    "field",
    "phenomenon",
    "standard",
    "term",
    "other",
}

type TopicContextGenerator = Callable[..., str]


def _unique(items: Iterable[str]) -> tuple[str, ...]:
    """문자열 순서를 유지하며 빈 값과 대소문자 중복을 제거한다."""
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).strip()
        marker = normalize_topic_keyword(value)
        if value and marker not in seen:
            result.append(value)
            seen.add(marker)
    return tuple(result)


def _string_list(value: object) -> tuple[str, ...]:
    """LLM JSON 배열을 길이가 제한된 문자열 Tuple로 정제한다."""
    if not isinstance(value, list):
        return ()
    return _unique(str(item) for item in value)[:5]


def _surface_index(
    contexts: Sequence[OnboardingTopicContext],
) -> dict[str, list[OnboardingTopicContext]]:
    """정식 Topic 이름과 별칭의 exact-match 색인을 만든다."""
    result: dict[str, list[OnboardingTopicContext]] = {}
    for context in contexts:
        for surface in (context.canonical_name, *context.aliases):
            result.setdefault(normalize_topic_keyword(surface), []).append(context)
    return result


def _existing_index(
    entries: Sequence[ExistingWikiEntry],
) -> dict[str, list[ExistingWikiEntry]]:
    """기존 Wiki 제목·별칭의 exact-match 색인을 만든다."""
    result: dict[str, list[ExistingWikiEntry]] = {}
    for entry in entries:
        raw_aliases = entry.metadata.get("aliases", [])
        aliases = raw_aliases if isinstance(raw_aliases, list) else []
        for surface in (entry.title, *(str(item) for item in aliases)):
            result.setdefault(normalize_topic_keyword(surface), []).append(entry)
    return result


def _context_from_existing(
    keyword: str, entry: ExistingWikiEntry
) -> OnboardingTopicContext:
    """기존 Wiki 노드를 새 Source가 다시 만들지 않도록 컨텍스트로 변환한다."""
    metadata = entry.metadata
    definition_key = "description" if entry.document_kind == "entity" else "definition"
    definition = str(metadata.get(definition_key) or entry.summary or "").strip()
    if not definition:
        definition = f"{entry.title}에 관해 사용자의 개인 Wiki에 이미 축적된 항목이다."
    return OnboardingTopicContext(
        original_keyword=keyword,
        canonical_name=entry.title,
        node_kind=entry.document_kind,
        subtype=entry.domain or "other",
        definition=definition,
        key_characteristics=_string_list(metadata.get("key_characteristics")),
        applications=_string_list(metadata.get("applications")),
        aliases=_string_list(metadata.get("aliases")),
        resolution_kind="existing_wiki",
        confidence=1.0,
        matched_existing_key=entry.document_key,
    )


def _parse_generated_contexts(
    raw_response: str,
    *,
    keywords: Sequence[str],
    taxonomy_version: str | None,
    locale: str,
    model: str,
) -> dict[str, OnboardingTopicContext]:
    """추가 키워드 Batch LLM 응답을 검증해 입력별 컨텍스트로 변환한다."""
    payload = json.loads(strip_json_fence(raw_response))
    rows = payload.get("topics") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("추가 Topic 컨텍스트 응답에 topics 배열이 없습니다.")
    requested = {normalize_topic_keyword(keyword): keyword for keyword in keywords}
    parsed: dict[str, OnboardingTopicContext] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        marker = normalize_topic_keyword(str(row.get("keyword") or ""))
        if not marker or marker not in requested or marker in parsed:
            continue
        canonical_name = str(row.get("canonical_name") or "").strip()
        definition = str(row.get("definition") or "").strip()
        node_kind = str(row.get("node_kind") or "concept").strip()
        subtype = str(row.get("subtype") or "other").strip()
        allowed_subtypes = (
            _ENTITY_SUBTYPES if node_kind == "entity" else _CONCEPT_SUBTYPES
        )
        if (
            not canonical_name
            or not definition
            or node_kind not in {"entity", "concept"}
            or subtype not in allowed_subtypes
        ):
            continue
        original_keyword = requested[marker]
        try:
            confidence = float(row.get("confidence", 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        signature = topic_context_signature(
            keyword=original_keyword,
            taxonomy_version=taxonomy_version,
            locale=locale,
            prompt_version=CUSTOM_TOPIC_PROMPT_VERSION,
        )
        parsed[marker] = OnboardingTopicContext(
            original_keyword=original_keyword,
            canonical_name=canonical_name,
            node_kind=node_kind,
            subtype=subtype,
            definition=definition,
            key_characteristics=_string_list(row.get("key_characteristics")),
            applications=_string_list(row.get("applications")),
            aliases=_string_list(row.get("aliases")),
            search_terms=_string_list(row.get("search_terms")),
            possible_meanings=_string_list(row.get("possible_meanings")),
            locale=locale,
            resolution_kind="llm_generated",
            confidence=max(0.0, min(1.0, confidence)),
            context_signature=signature,
            model_name=model,
            prompt_version=CUSTOM_TOPIC_PROMPT_VERSION,
        )
    return parsed


def _generic_context(
    keyword: str,
    *,
    taxonomy_version: str | None,
    locale: str,
    model: str,
    reason: str,
) -> OnboardingTopicContext:
    """LLM 실패·누락 시에도 Wiki Build를 계속할 일반론 컨텍스트를 만든다."""
    signature = topic_context_signature(
        keyword=keyword,
        taxonomy_version=taxonomy_version,
        locale=locale,
        prompt_version=CUSTOM_TOPIC_PROMPT_VERSION,
    )
    return OnboardingTopicContext(
        original_keyword=keyword,
        canonical_name=keyword,
        node_kind="concept",
        subtype="term",
        definition=(
            f"{keyword}에 관한 일반적인 배경, 핵심 개념과 사용 맥락을 탐색하기 위한 "
            "관심 주제다. 의미가 여러 개인 경우 후속 자료의 문맥으로 범위를 구체화한다."
        ),
        key_characteristics=("일반적 배경", "핵심 개념", "문맥에 따른 의미 구체화"),
        applications=("관련 자료 탐색", "개인 지식 연결"),
        possible_meanings=(f"'{keyword}'가 가리키는 일반 개념 또는 고유 대상",),
        locale=locale,
        resolution_kind="generic_fallback",
        confidence=0.35,
        context_signature=signature,
        model_name=model,
        prompt_version=CUSTOM_TOPIC_PROMPT_VERSION,
        metadata={"fallback_reason": reason},
    )


def resolve_onboarding_contexts(
    *,
    selected_topic_ids: Sequence[str],
    custom_keywords: Sequence[str],
    taxonomy_version: str | None,
    locale: str,
    taxonomy_contexts: Sequence[OnboardingTopicContext],
    cached_contexts: Sequence[OnboardingTopicContext],
    existing_entries: Sequence[ExistingWikiEntry],
    model: str = "gpt-4.1-mini",
    generator: TopicContextGenerator = complete,
) -> OnboardingContextResolution:
    """정식 Topic과 추가 키워드를 우선순위가 고정된 규칙으로 해석한다."""
    official_by_id = {
        context.topic_id: context
        for context in taxonomy_contexts
        if context.topic_id is not None
    }
    missing_ids = [
        topic_id for topic_id in selected_topic_ids if topic_id not in official_by_id
    ]
    if missing_ids:
        raise ValueError(
            "결정론적 온보딩 Topic 컨텍스트가 없습니다: " + ", ".join(missing_ids)
        )
    resolved: list[OnboardingTopicContext] = [
        official_by_id[topic_id]
        for topic_id in dict.fromkeys(selected_topic_ids)
    ]
    generated: list[OnboardingTopicContext] = []
    warnings: list[str] = []

    taxonomy_surfaces = _surface_index(taxonomy_contexts)
    existing_surfaces = _existing_index(existing_entries)
    cache_by_keyword: dict[str, OnboardingTopicContext] = {}
    for context in cached_contexts:
        cache_by_keyword.setdefault(
            normalize_topic_keyword(context.original_keyword), context
        )
    unresolved: list[str] = []
    for keyword in _unique(custom_keywords):
        marker = normalize_topic_keyword(keyword)
        taxonomy_matches = taxonomy_surfaces.get(marker, [])
        if len(taxonomy_matches) == 1:
            resolved.append(
                replace(
                    taxonomy_matches[0],
                    original_keyword=keyword,
                    resolution_kind="taxonomy_alias",
                )
            )
            continue
        existing_matches = existing_surfaces.get(marker, [])
        if len(existing_matches) == 1:
            resolved.append(_context_from_existing(keyword, existing_matches[0]))
            continue
        expected_signature = topic_context_signature(
            keyword=keyword,
            taxonomy_version=taxonomy_version,
            locale=locale,
            prompt_version=CUSTOM_TOPIC_PROMPT_VERSION,
        )
        cached = cache_by_keyword.get(marker)
        if cached is not None and cached.context_signature == expected_signature:
            resolved.append(cached)
            continue
        unresolved.append(keyword)

    llm_generated: dict[str, OnboardingTopicContext] = {}
    llm_error: str | None = None
    if unresolved:
        user_prompt = json.dumps(
            {"locale": locale, "keywords": unresolved},
            ensure_ascii=False,
        )
        try:
            raw_response = generator(_SYSTEM_PROMPT, user_prompt, model=model)
            llm_generated = _parse_generated_contexts(
                raw_response,
                keywords=unresolved,
                taxonomy_version=taxonomy_version,
                locale=locale,
                model=model,
            )
        except Exception as error:  # noqa: BLE001 - 일반론 폴백이 회복 경로다.
            llm_error = str(error)
            warnings.append(f"추가 Topic 컨텍스트 LLM 실패: {error}")

    for keyword in unresolved:
        marker = normalize_topic_keyword(keyword)
        context = llm_generated.get(marker)
        if context is None:
            reason = llm_error or "LLM 응답에서 입력 키워드가 누락됨"
            context = _generic_context(
                keyword,
                taxonomy_version=taxonomy_version,
                locale=locale,
                model=model,
                reason=reason,
            )
            warnings.append(f"'{keyword}'에 일반론 컨텍스트를 사용했습니다.")
        resolved.append(context)
        generated.append(context)

    trace = ONBOARDING_CONTEXT_MODEL
    if unresolved:
        trace = f"{model};prompt={CUSTOM_TOPIC_PROMPT_VERSION}"
    unique_resolved: list[OnboardingTopicContext] = []
    seen_contexts: set[tuple[str, str]] = set()
    for context in resolved:
        identity = (
            context.topic_id
            or context.matched_existing_key
            or normalize_topic_keyword(context.canonical_name)
        )
        marker = (context.node_kind, identity)
        if marker in seen_contexts:
            continue
        seen_contexts.add(marker)
        unique_resolved.append(context)
    return OnboardingContextResolution(
        contexts=tuple(unique_resolved),
        generated_contexts=tuple(generated),
        model_trace=trace,
        warnings=tuple(dict.fromkeys(warnings)),
    )
