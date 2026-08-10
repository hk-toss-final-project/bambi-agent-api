"""온보딩 정식 Topic 컨텍스트와 사용자 추가 키워드 캐시 영속화."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from shared.onboarding_context_models import (
    OnboardingTopicContext,
    normalize_topic_keyword,
)

type DictRow = dict[str, Any]


def _strings(value: object) -> tuple[str, ...]:
    """JSON 배열 값을 빈 값 없는 문자열 Tuple로 변환한다."""
    if not isinstance(value, list):
        return ()
    return tuple(text for item in value if (text := str(item).strip()))


def _unique_strings(values: Sequence[str]) -> tuple[str, ...]:
    """대소문자 중복을 제거한 문자열 Tuple을 입력 순서대로 만든다."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        marker = normalize_topic_keyword(value)
        if value and marker not in seen:
            result.append(value)
            seen.add(marker)
    return tuple(result)


async def list_onboarding_topic_contexts(
    connection: AsyncConnection[DictRow],
    *,
    taxonomy_version: str,
    locale: str,
) -> list[OnboardingTopicContext]:
    """한 taxonomy 버전의 활성 결정론적 Topic 컨텍스트를 모두 조회한다.

    전체 목록을 읽는 이유는 선택한 정식 Topic뿐 아니라 사용자 추가 키워드가
    정식 Topic의 이름·별칭과 정확히 같은지도 한 번에 판정하기 위해서다.
    """
    cursor = await connection.execute(
        """
        SELECT
            context.taxonomy_version,
            context.topic_id,
            context.locale,
            context.canonical_name,
            context.node_kind,
            context.subtype,
            context.definition,
            context.key_characteristics,
            context.applications,
            context.aliases,
            context.related_topic_ids,
            context.content_version,
            topic.name AS taxonomy_name,
            topic.name_en AS taxonomy_name_en,
            topic.keywords AS taxonomy_keywords
        FROM agent.onboarding_topic_contexts AS context
        LEFT JOIN agent.interest_taxonomy_topics AS topic
          ON topic.taxonomy_version = context.taxonomy_version
         AND topic.topic_id = context.topic_id
        WHERE context.taxonomy_version = %s
          AND context.locale = %s
          AND context.enabled
        ORDER BY context.topic_id
        """,
        (taxonomy_version, locale),
    )
    rows = await cursor.fetchall()
    return [
        OnboardingTopicContext(
            original_keyword=str(row["canonical_name"]),
            canonical_name=str(row["canonical_name"]),
            node_kind=str(row["node_kind"]),
            subtype=str(row["subtype"]),
            definition=str(row["definition"]),
            key_characteristics=_strings(row["key_characteristics"]),
            applications=_strings(row["applications"]),
            aliases=_unique_strings(
                (
                    *_strings(row["aliases"]),
                    str(row.get("taxonomy_name") or "").strip(),
                    str(row.get("taxonomy_name_en") or "").strip(),
                    *_strings(row.get("taxonomy_keywords")),
                )
            ),
            related_topic_ids=_strings(row["related_topic_ids"]),
            taxonomy_version=str(row["taxonomy_version"]),
            topic_id=str(row["topic_id"]),
            locale=str(row["locale"]),
            content_version=int(row["content_version"]),
            resolution_kind="deterministic_topic",
            confidence=1.0,
        )
        for row in rows
    ]


async def list_cached_custom_topic_contexts(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    keywords: Sequence[str],
    locale: str,
) -> list[OnboardingTopicContext]:
    """사용자·locale에 대해 현재 활성인 추가 키워드 컨텍스트를 조회한다."""
    normalized = sorted(
        {
            value
            for keyword in keywords
            if (value := normalize_topic_keyword(keyword))
        }
    )
    if not normalized:
        return []
    cursor = await connection.execute(
        """
        SELECT
            original_keyword,
            normalized_keyword,
            locale,
            context_signature,
            canonical_name,
            node_kind,
            subtype,
            definition,
            key_characteristics,
            applications,
            aliases,
            search_terms,
            possible_meanings,
            resolution_kind,
            confidence,
            model_name,
            prompt_version,
            metadata
        FROM agent.user_custom_topic_contexts
        WHERE user_id = %s
          AND normalized_keyword = ANY(%s)
          AND locale = %s
          AND status = 'active'
        ORDER BY updated_at DESC, id DESC
        """,
        (user_id, normalized, locale),
    )
    rows = await cursor.fetchall()
    return [
        OnboardingTopicContext(
            original_keyword=str(row["original_keyword"]),
            canonical_name=str(row["canonical_name"]),
            node_kind=str(row["node_kind"]),
            subtype=str(row["subtype"]),
            definition=str(row["definition"]),
            key_characteristics=_strings(row["key_characteristics"]),
            applications=_strings(row["applications"]),
            aliases=_strings(row["aliases"]),
            search_terms=_strings(row["search_terms"]),
            possible_meanings=_strings(row["possible_meanings"]),
            locale=str(row["locale"]),
            resolution_kind=str(row["resolution_kind"]),
            confidence=float(row["confidence"]),
            context_signature=str(row["context_signature"]),
            model_name=(str(row["model_name"]) if row["model_name"] else None),
            prompt_version=(
                str(row["prompt_version"]) if row["prompt_version"] else None
            ),
            metadata=dict(row["metadata"] or {}),
        )
        for row in rows
    ]


async def save_custom_topic_contexts(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    contexts: Sequence[OnboardingTopicContext],
) -> int:
    """새로 생성·폴백한 사용자 키워드 컨텍스트를 활성 캐시로 저장한다."""
    saved_count = 0
    for context in contexts:
        if not context.context_signature:
            raise ValueError("사용자 추가 키워드 컨텍스트에 서명이 없습니다.")
        normalized_keyword = normalize_topic_keyword(context.original_keyword)
        await connection.execute(
            """
            UPDATE agent.user_custom_topic_contexts
            SET status = 'superseded', updated_at = clock_timestamp()
            WHERE user_id = %s
              AND normalized_keyword = %s
              AND locale = %s
              AND status = 'active'
              AND context_signature <> %s
            """,
            (
                user_id,
                normalized_keyword,
                context.locale,
                context.context_signature,
            ),
        )
        cursor = await connection.execute(
            """
            INSERT INTO agent.user_custom_topic_contexts (
                user_id,
                original_keyword,
                normalized_keyword,
                locale,
                context_signature,
                canonical_name,
                node_kind,
                subtype,
                definition,
                key_characteristics,
                applications,
                aliases,
                search_terms,
                possible_meanings,
                resolution_kind,
                confidence,
                model_name,
                prompt_version,
                metadata
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (
                user_id, normalized_keyword, locale, context_signature
            ) WHERE status = 'active'
            DO UPDATE SET
                original_keyword = EXCLUDED.original_keyword,
                canonical_name = EXCLUDED.canonical_name,
                node_kind = EXCLUDED.node_kind,
                subtype = EXCLUDED.subtype,
                definition = EXCLUDED.definition,
                key_characteristics = EXCLUDED.key_characteristics,
                applications = EXCLUDED.applications,
                aliases = EXCLUDED.aliases,
                search_terms = EXCLUDED.search_terms,
                possible_meanings = EXCLUDED.possible_meanings,
                resolution_kind = EXCLUDED.resolution_kind,
                confidence = EXCLUDED.confidence,
                model_name = EXCLUDED.model_name,
                prompt_version = EXCLUDED.prompt_version,
                metadata = EXCLUDED.metadata,
                updated_at = clock_timestamp()
            RETURNING id
            """,
            (
                user_id,
                context.original_keyword,
                normalized_keyword,
                context.locale,
                context.context_signature,
                context.canonical_name,
                context.node_kind,
                context.subtype,
                context.definition,
                Jsonb(list(context.key_characteristics)),
                Jsonb(list(context.applications)),
                Jsonb(list(context.aliases)),
                Jsonb(list(context.search_terms)),
                Jsonb(list(context.possible_meanings)),
                context.resolution_kind,
                context.confidence,
                context.model_name,
                context.prompt_version,
                Jsonb(context.metadata),
            ),
        )
        if await cursor.fetchone() is not None:
            saved_count += 1
    return saved_count
