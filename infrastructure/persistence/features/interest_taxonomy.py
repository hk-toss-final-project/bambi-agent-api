"""관심사 taxonomy Snapshot과 Topic 수집 구독 영속화."""

import hashlib
from dataclasses import dataclass
from typing import Any, Sequence

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

type DictRow = dict[str, Any]


class InterestTaxonomyConflictError(RuntimeError):
    """같은 taxonomy 버전에 다른 원본 Hash가 전달된 오류."""


@dataclass(frozen=True, slots=True)
class StoredInterestTaxonomy:
    """Agent DB에 보관한 taxonomy Snapshot 요약."""

    version: str
    source_hash: str
    category_count: int
    topic_count: int


def _taxonomy_target_key(version: str, topic_id: str) -> str:
    """버전과 Topic ID로 안정적인 수집 대상 Key를 만든다."""
    return f"taxonomy:{version}:{topic_id}"


def _custom_target_key(topic: str) -> str:
    """사용자 추가 Topic을 정규화한 비식별 수집 대상 Key를 만든다."""
    normalized = " ".join(topic.casefold().split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"custom:{digest}"


async def upsert_interest_taxonomy_snapshot(
    connection: AsyncConnection[DictRow],
    *,
    version: str,
    source_hash: str,
    locale: str,
    categories: Sequence[dict[str, Any]],
) -> StoredInterestTaxonomy:
    """Service taxonomy를 버전 단위 불변 Snapshot과 선수집 대상으로 저장한다."""
    await connection.execute(
        """
        INSERT INTO agent.interest_taxonomy_versions (version, source_hash, locale)
        VALUES (%s, %s, %s)
        ON CONFLICT (version) DO NOTHING
        """,
        (version, source_hash, locale),
    )
    version_cursor = await connection.execute(
        """
        SELECT source_hash
        FROM agent.interest_taxonomy_versions
        WHERE version = %s
        """,
        (version,),
    )
    stored_version = await version_cursor.fetchone()
    if stored_version is None or stored_version["source_hash"] != source_hash:
        raise InterestTaxonomyConflictError(version)

    topic_count = 0
    for category in categories:
        category_id = str(category["id"])
        await connection.execute(
            """
            INSERT INTO agent.interest_taxonomy_categories (
                taxonomy_version, category_id, name, name_en, description,
                emoji, display_order
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (taxonomy_version, category_id) DO NOTHING
            """,
            (
                version,
                category_id,
                category["name"],
                category["name_en"],
                category["description"],
                category["emoji"],
                category["order"],
            ),
        )
        for topic in category.get("topics", []):
            topic_count += 1
            topic_id = str(topic["id"])
            await connection.execute(
                """
                INSERT INTO agent.interest_taxonomy_topics (
                    taxonomy_version, topic_id, category_id, name, name_en,
                    description, display_order, keywords
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (taxonomy_version, topic_id) DO NOTHING
                """,
                (
                    version,
                    topic_id,
                    category_id,
                    topic["name"],
                    topic["name_en"],
                    topic["description"],
                    topic["order"],
                    Jsonb(list(topic.get("keywords", []))),
                ),
            )
            await connection.execute(
                """
                INSERT INTO agent.interest_collection_targets (
                    target_key, target_type, taxonomy_version, topic_id,
                    category_id, query, category_name
                ) VALUES (%s, 'taxonomy', %s, %s, %s, %s, %s)
                ON CONFLICT (target_key) DO NOTHING
                """,
                (
                    _taxonomy_target_key(version, topic_id),
                    version,
                    topic_id,
                    category_id,
                    topic["name"],
                    category["name"],
                ),
            )
    return StoredInterestTaxonomy(
        version=version,
        source_hash=source_hash,
        category_count=len(categories),
        topic_count=topic_count,
    )


async def sync_user_interest_subscriptions(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    context_snapshot_id: str,
    interest_taxonomy_version: str | None,
    selected_topic_ids: Sequence[str],
    signup_interests: Sequence[dict[str, Any]],
) -> None:
    """최신 컨텍스트의 taxonomy/custom Topic을 수집 대상 구독으로 동기화한다."""
    desired: dict[str, tuple[str, str | None]] = {}
    taxonomy_topic_names: set[str] = set()
    if interest_taxonomy_version and selected_topic_ids:
        cursor = await connection.execute(
            """
            SELECT topic.topic_id, topic.name, category.name AS category_name
            FROM agent.interest_taxonomy_topics AS topic
            JOIN agent.interest_taxonomy_categories AS category
              ON category.taxonomy_version = topic.taxonomy_version
             AND category.category_id = topic.category_id
            WHERE topic.taxonomy_version = %s
              AND topic.topic_id = ANY(%s)
            """,
            (interest_taxonomy_version, list(selected_topic_ids)),
        )
        rows = await cursor.fetchall()
        if len(rows) != len(set(selected_topic_ids)):
            raise ValueError("컨텍스트에 Agent taxonomy Snapshot에 없는 Topic ID가 있습니다.")
        for row in rows:
            topic_name = str(row["name"])
            taxonomy_topic_names.add(topic_name.casefold())
            desired[_taxonomy_target_key(interest_taxonomy_version, row["topic_id"])] = (
                topic_name,
                str(row["category_name"]),
            )

    for group in signup_interests:
        for raw_topic in group.get("topics", []):
            topic_name = " ".join(str(raw_topic).split())
            if not topic_name or topic_name.casefold() in taxonomy_topic_names:
                continue
            target_key = _custom_target_key(topic_name)
            await connection.execute(
                """
                INSERT INTO agent.interest_collection_targets (
                    target_key, target_type, query, category_name
                ) VALUES (%s, 'custom', %s, NULL)
                ON CONFLICT (target_key) DO UPDATE SET
                    status = 'active',
                    query = EXCLUDED.query
                """,
                (target_key, topic_name),
            )
            desired[target_key] = (topic_name, None)

    await connection.execute(
        """
        UPDATE agent.user_interest_subscriptions
        SET active = false
        WHERE user_id = %s AND active
        """,
        (user_id,),
    )
    for target_key, (topic_name, category_name) in desired.items():
        await connection.execute(
            """
            INSERT INTO agent.user_interest_subscriptions (
                user_id, target_key, context_snapshot_id, topic_name,
                category_name, active
            ) VALUES (%s, %s, %s, %s, %s, true)
            """,
            (
                user_id,
                target_key,
                context_snapshot_id,
                topic_name,
                category_name,
            ),
        )
    await connection.execute(
        """
        UPDATE agent.interest_collection_targets AS target
        SET subscriber_count = counts.subscriber_count
        FROM (
            SELECT candidate.target_key, count(subscription.id)::integer AS subscriber_count
            FROM agent.interest_collection_targets AS candidate
            LEFT JOIN agent.user_interest_subscriptions AS subscription
              ON subscription.target_key = candidate.target_key AND subscription.active
            GROUP BY candidate.target_key
        ) AS counts
        WHERE counts.target_key = target.target_key
          AND target.subscriber_count <> counts.subscriber_count
        """
    )
