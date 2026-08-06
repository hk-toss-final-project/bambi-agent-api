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

    # 온보딩에서 온 구독만 갈아 끼운다. 개인 Wiki 관심사에서 자동 등록한 구독
    # (origin='wiki_interest')까지 지우면, 컨텍스트를 저장할 때마다 창고가 따라가던
    # 주제가 사라진다.
    await connection.execute(
        """
        UPDATE agent.user_interest_subscriptions
        SET active = false
        WHERE user_id = %s AND active AND origin = 'onboarding'
        """,
        (user_id,),
    )
    for target_key, (topic_name, category_name) in desired.items():
        await connection.execute(
            """
            INSERT INTO agent.user_interest_subscriptions (
                user_id, target_key, context_snapshot_id, topic_name,
                category_name, active, origin
            ) VALUES (%s, %s, %s, %s, %s, true, 'onboarding')
            ON CONFLICT (user_id, target_key) WHERE active DO NOTHING
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


# 개인 Wiki 관심사에서 자동 등록할 수집 대상 상한. 관심사는 Wiki 노드 제목에서
# 나오므로 사용자가 글을 저장할수록 계속 늘어난다. 상한이 없으면 수집 대상이
# 사용자 수 × 노드 수로 불어나 외부 API 한도를 먹는다.
_WIKI_INTEREST_TARGET_LIMIT = 5
# 점수는 최상위를 1.0으로 재정규화한 값이다. 한 번 저장하고 만 주제까지 창고가
# 따라가지 않도록 하한을 둔다.
_WIKI_INTEREST_SCORE_FLOOR = 0.3


async def sync_wiki_interest_collection_targets(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    interests: Sequence[dict[str, Any]],
    limit: int = _WIKI_INTEREST_TARGET_LIMIT,
    score_floor: float = _WIKI_INTEREST_SCORE_FLOOR,
) -> list[str]:
    """개인 Wiki 상위 관심사를 창고 수집 대상으로 등록하고 구독을 갱신한다.

    창고를 채우는 말과 관심사를 뽑는 말이 서로 달라서 생기는 구멍을 메운다.
    수집 대상은 온보딩에서 고른 taxonomy 라벨("프로야구")인데, 관심사 점수는
    개인 Wiki 노드 제목("오스틴딘")에서 나온다. 사용자가 글을 저장할수록 세밀한
    노드가 상위로 올라오고, 그 주제로는 아무도 수집하고 있지 않아 리포트가
    근거를 못 찾는다. 상위 관심사를 수집 대상에 얹어 창고가 따라가게 한다.

    이미 같은 검색어로 수집 중인 대상이 있으면 새로 만들지 않고 그 대상을
    구독한다 — 같은 말로 두 번 수집하면 외부 API 호출만 두 배가 된다.

    Args:
        connection: 이미 열린 agent-db 커넥션
        user_id: 대상 사용자 ID
        interests: INT-011이 계산한 관심사 목록(점수 내림차순, topic·score 키 사용)
        limit: 자동 등록할 최대 주제 수
        score_floor: 이 점수 미만인 관심사는 등록하지 않는다

    Returns:
        이번에 구독한 주제 이름 목록(점수 순). 등록할 게 없으면 빈 목록
    """
    # 수집 대상 쓰기는 RLS가 system scope를 요구한다(interest_collection_target_write).
    # 이 함수는 Wiki Build 직후 user scope 커넥션에서 불리므로 여기서 scope를 올린다.
    #
    # 자기 트랜잭션을 여는 이유는 두 가지다. SET LOCAL이 트랜잭션 안에서만 살고,
    # 실패가 이 트랜잭션 안에서 끝나야 하기 때문이다. 감싸지 않으면 SQL 하나가
    # 실패했을 때 커넥션 전체가 실패 상태가 되고, 호출자가 이어서 하는 Job 완료
    # 기록까지 막힌다(2026-08-06 실측: 위키 노드는 저장됐는데 Job이 완료로 넘어가지
    # 못해 lease 만료 → 재실행이 반복됐다).
    candidates: list[str] = []
    seen: set[str] = set()
    for interest in interests:
        topic_name = " ".join(str(interest.get("topic") or "").split())
        if not topic_name:
            continue
        try:
            score = float(interest.get("score") or 0.0)
        except (TypeError, ValueError):
            continue
        if score < score_floor:
            continue
        marker = topic_name.casefold()
        if marker in seen:
            continue
        seen.add(marker)
        candidates.append(topic_name)
        if len(candidates) >= limit:
            break
    if not candidates:
        return []

    async with connection.transaction():
        await connection.execute("SET LOCAL app.access_scope = 'system'")
        return await _register_wiki_interest_targets(
            connection, user_id=user_id, candidates=candidates
        )


async def _register_wiki_interest_targets(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    candidates: list[str],
) -> list[str]:
    """system scope 트랜잭션 안에서 수집 대상 등록과 구독 갱신을 수행한다."""
    # 구독 행은 컨텍스트 Snapshot을 참조한다(NOT NULL). 컨텍스트가 아직 없는
    # 사용자는 구독을 만들 수 없으므로 조용히 건너뛴다 — 관심사 재계산 자체를
    # 실패시킬 이유는 없다.
    context_cursor = await connection.execute(
        """
        SELECT id
        FROM agent.user_context_snapshots
        WHERE user_id = %s AND deleted_at IS NULL
        ORDER BY context_version DESC
        LIMIT 1
        """,
        (user_id,),
    )
    context = await context_cursor.fetchone()
    if context is None:
        return []

    # 같은 검색어로 이미 수집 중인 대상이 있으면 재사용한다.
    existing_cursor = await connection.execute(
        """
        SELECT target_key, lower(btrim(query)) AS normalized_query
        FROM agent.interest_collection_targets
        WHERE status = 'active'
          AND lower(btrim(query)) = ANY(%s)
        """,
        ([name.casefold().strip() for name in candidates],),
    )
    reusable = {
        str(row["normalized_query"]): str(row["target_key"])
        for row in await existing_cursor.fetchall()
    }

    desired: list[tuple[str, str]] = []
    for topic_name in candidates:
        target_key = reusable.get(topic_name.casefold().strip())
        if target_key is None:
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
        desired.append((target_key, topic_name))

    await connection.execute(
        """
        UPDATE agent.user_interest_subscriptions
        SET active = false
        WHERE user_id = %s AND active AND origin = 'wiki_interest'
        """,
        (user_id,),
    )
    for target_key, topic_name in desired:
        # 온보딩에서 이미 구독 중인 대상이면 그대로 둔다((user_id, target_key)에
        # 활성 행이 하나만 있을 수 있고, 어느 쪽이든 수집은 이미 돌고 있다).
        await connection.execute(
            """
            INSERT INTO agent.user_interest_subscriptions (
                user_id, target_key, context_snapshot_id, topic_name,
                category_name, active, origin
            ) VALUES (%s, %s, %s, %s, NULL, true, 'wiki_interest')
            ON CONFLICT (user_id, target_key) WHERE active DO NOTHING
            """,
            (user_id, target_key, context["id"], topic_name),
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
    return [topic_name for _, topic_name in desired]
