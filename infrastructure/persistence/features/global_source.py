"""기능 구현 모듈.

DB-008, DB-009, DB-010, DB-011, DB-012, DB-013, DB-014 기능의 실제 구현 위치를 제공한다.

이 파일은 위 스캐폴드 기능 함수와 함께, Global Source Collector Worker가
GDELT·Naver로 수집한 뉴스 URL을 소유권 없는 수집 캐시
(`agent.global_source_documents`)에 저장하고, Jina Reader Worker가 그 URL의
본문을 채우기 위해 사용하는 실제 PostgreSQL 함수를 제공한다.

수집 캐시는 LLM Wiki가 아니다. Wiki(`wiki_documents`)는 맥락 주체(개인·팀)
별 LLM 파생 노드를 담고, 이 캐시는 "LLM이 URL을 직접 읽을 수 없으니 한 번
읽은 본문을 모두가 재사용"하기 위한 원문 풀이다 (0008 Migration 참조).

수집과 본문 채우기는 두 단계로 분리된다.
1. 수집 워커: URL 기준으로 중복을 제거하고, 아직 본문이 없는 문서를
   `content_status = 'pending'` 상태로 저장한다.
2. Jina 워커: pending 문서를 점유(`fetching`)해 본문 Markdown을 채우고
   `content_status = 'fetched'`로 전환한다.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from shared.hashing import compute_content_hash
from infrastructure.sources.connectors.api import LatestArticle
from shared.contracts import FeatureRequest, FeatureResult

type DictRow = dict[str, Any]


@dataclass(frozen=True, slots=True)
class GlobalArticleToFetch:
    """본문 수집 Worker가 채울 대상으로 점유한 Global 문서 하나.

    provider는 본문을 어떻게 가져올지 고르는 데 쓴다. 뉴스·Reddit은 페이지
    본문(Jina Reader)이 그대로 쓸 만하지만 YouTube는 영상 페이지라 자막을
    가져와야 한다.
    """

    document_id: str
    url: str
    provider: str = ""


@dataclass(frozen=True, slots=True)
class GlobalCollectionSchedule:
    """Scheduler가 정기 수집을 판단할 때 필요한 Source 하나의 스케줄 설정.

    수집 주기·키워드·쿼터는 모두 `agent.global_sources` row에 있고, 마지막
    실행 시각과 오늘 실행 횟수는 `agent.global_collection_runs`에서 집계한다.
    """

    source_id: str
    source_key: str
    provider: str
    schedule_cron: str
    keywords: tuple[str, ...]
    language: str | None
    limit_per_provider: int
    daily_max_runs: int | None
    last_started_at: datetime | None
    runs_today: int
    status: str = "active"
    display_name: str = ""
    # SNS Provider(youtube·reddit)의 검색 범위·정렬 설정. Worker의 기본값을
    # Source별로 덮어쓴다. connector_config.search_options에서 읽는다.
    search_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GlobalCollectionRunRecord:
    """수집 실행 이력 한 건. Service가 스케줄 동작을 확인할 때 사용한다."""

    run_id: str
    source_key: str
    query: str | None
    status: str
    fetched_count: int
    created_count: int
    duplicate_count: int
    failed_count: int
    error_code: str | None
    started_at: datetime
    completed_at: datetime | None


# Source 설정에 별도 지정이 없을 때 한 번에 수집할 Provider당 기사 수.
_DEFAULT_LIMIT_PER_PROVIDER = 10


def _document_key(url: str) -> str:
    """URL을 안정적인 24자 캐시 Key로 변환한다."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def _positive_int(value: object, default: int | None) -> int | None:
    """설정 값이 양의 정수일 때만 사용하고 아니면 기본값을 돌려준다."""
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if value > 0 else default


def _to_schedule(row: DictRow) -> GlobalCollectionSchedule:
    """global_sources 조회 Row를 스케줄 설정 값 객체로 변환한다."""
    connector_config = row.get("connector_config") or {}
    quota_policy = row.get("quota_policy") or {}
    languages = row.get("languages") or []
    keywords = tuple(
        keyword.strip()
        for keyword in (row.get("keywords") or [])
        if keyword and keyword.strip()
    )
    return GlobalCollectionSchedule(
        source_id=str(row["id"]),
        source_key=row["source_key"],
        provider=row["connector_type"],
        schedule_cron=(row.get("schedule_cron") or "").strip(),
        keywords=keywords,
        language=languages[0] if languages else None,
        limit_per_provider=_positive_int(
            connector_config.get("limit_per_provider"),
            _DEFAULT_LIMIT_PER_PROVIDER,
        ),
        daily_max_runs=_positive_int(quota_policy.get("daily_max_runs"), None),
        last_started_at=row.get("last_started_at"),
        runs_today=int(row.get("runs_today") or 0),
        status=row.get("status") or "active",
        display_name=row.get("display_name") or "",
        search_options=dict(connector_config.get("search_options") or {}),
    )


# 스케줄 설정과 실행 이력 집계를 함께 읽는 공통 조회. 뒤에 WHERE 절을 붙인다.
_SCHEDULE_SELECT = """
        SELECT
            source.id,
            source.source_key,
            source.connector_type,
            source.display_name,
            source.status,
            source.schedule_cron,
            CASE
                WHEN source.source_key = 'interest-taxonomy-google-news'
                    THEN source.keywords || COALESCE(due_targets.keywords, '{}')
                ELSE source.keywords
            END AS keywords,
            source.languages,
            source.quota_policy,
            source.connector_config,
            last_run.started_at AS last_started_at,
            COALESCE(today.run_count, 0) AS runs_today
        FROM agent.global_sources AS source
        LEFT JOIN LATERAL (
            SELECT run.started_at
            FROM agent.global_collection_runs AS run
            WHERE run.source_id = source.id
            ORDER BY run.started_at DESC
            LIMIT 1
        ) AS last_run ON true
        LEFT JOIN LATERAL (
            SELECT count(*) AS run_count
            FROM agent.global_collection_runs AS run
            WHERE run.source_id = source.id
              AND run.started_at >= date_trunc('day', clock_timestamp())
        ) AS today ON true
        LEFT JOIN LATERAL (
            SELECT array_agg(
                target.query
                ORDER BY target.subscriber_count DESC, target.priority, target.target_key
            )
                AS keywords
            FROM (
                SELECT
                    collection_target.target_key,
                    collection_target.query,
                    collection_target.subscriber_count,
                    collection_target.next_collection_at AS priority
                FROM agent.interest_collection_targets AS collection_target
                WHERE collection_target.status = 'active'
                  AND collection_target.preferred_provider = source.connector_type
                  AND collection_target.next_collection_at <= clock_timestamp()
                ORDER BY
                    collection_target.subscriber_count DESC,
                    collection_target.next_collection_at,
                    collection_target.target_key
                LIMIT 50
            ) AS target
        ) AS due_targets
          ON source.source_key = 'interest-taxonomy-google-news'
"""


async def load_collection_schedules(
    connection: AsyncConnection[DictRow],
    *,
    only_scheduled: bool = True,
) -> list[GlobalCollectionSchedule]:
    """Global Source의 수집 스케줄 설정을 읽는다.

    기본값은 Scheduler가 쓰는 조건이다 — status가 active이고 `schedule_cron`이
    설정된 Source만 반환한다. Source별로 마지막 수집 실행 시각과 오늘 실행
    횟수를 함께 집계해, 다음 실행 시각 계산(Cron)과 일일 호출 한도 판정을 한
    번의 조회로 끝낸다.

    `only_scheduled=False`는 Service의 스케줄 조회(SCH-022)용이다. 주기가 아직
    없거나 중지된 Source도 함께 보여 줘야 조정할 대상을 찾을 수 있다.

    Args:
        connection: Agent DB 연결
        only_scheduled: True면 활성·주기 설정된 Source만 반환한다

    Returns:
        source_key 순으로 정렬한 수집 스케줄 목록
    """
    condition = (
        """
        WHERE source.status = 'active'
          AND source.schedule_cron IS NOT NULL
          AND btrim(source.schedule_cron) <> ''
        """
        if only_scheduled
        else "WHERE source.status <> 'deleted'"
    )
    cursor = await connection.execute(
        f"{_SCHEDULE_SELECT}{condition} ORDER BY source.source_key"
    )
    return [_to_schedule(row) for row in await cursor.fetchall()]


async def load_collection_schedule(
    connection: AsyncConnection[DictRow], *, source_key: str
) -> GlobalCollectionSchedule | None:
    """source_key로 수집 스케줄 설정 하나를 읽는다. 없으면 None."""
    cursor = await connection.execute(
        f"{_SCHEDULE_SELECT} WHERE source.source_key = %s",
        (source_key,),
    )
    row = await cursor.fetchone()
    return _to_schedule(row) if row is not None else None


async def upsert_collection_schedule(
    connection: AsyncConnection[DictRow],
    *,
    source_key: str,
    provider: str,
    display_name: str | None = None,
    schedule_cron: str,
    keywords: list[str],
    language: str | None = None,
    limit_per_provider: int | None = None,
    daily_max_runs: int | None = None,
) -> GlobalCollectionSchedule:
    """수집 스케줄을 등록하거나 같은 source_key의 설정을 덮어쓴다.

    Source row는 수집 Worker가 첫 수집 때 자동으로 만들기도 하므로, 등록은
    INSERT가 아니라 멱등 Upsert로 처리한다. 등록 시 status는 active로 되돌린다.

    Args:
        connection: Agent DB 연결
        source_key: Source 식별 Key (예: latest-naver)
        provider: 수집 Provider 이름 (connector_type)
        display_name: 화면에 보일 이름 (없으면 Provider 기준 기본값)
        schedule_cron: 수집 주기 Cron 식
        keywords: 각각 따로 수집할 키워드 목록
        language: 검색 언어 힌트
        limit_per_provider: 한 번에 수집할 기사 수
        daily_max_runs: 하루 최대 실행 횟수

    Returns:
        저장된 스케줄 설정
    """
    await connection.execute(
        """
        INSERT INTO agent.global_sources (
            source_key,
            connector_type,
            display_name,
            status,
            schedule_cron,
            keywords,
            languages,
            quota_policy,
            connector_config
        ) VALUES (%s, %s, %s, 'active', %s, %s, %s, %s, %s)
        ON CONFLICT (source_key) DO UPDATE SET
            connector_type = EXCLUDED.connector_type,
            display_name = EXCLUDED.display_name,
            status = 'active',
            schedule_cron = EXCLUDED.schedule_cron,
            keywords = EXCLUDED.keywords,
            languages = EXCLUDED.languages,
            quota_policy = agent.global_sources.quota_policy
                || EXCLUDED.quota_policy,
            connector_config = agent.global_sources.connector_config
                || EXCLUDED.connector_config,
            updated_at = clock_timestamp()
        """,
        (
            source_key,
            provider,
            display_name or f"Latest {provider}",
            schedule_cron,
            keywords,
            [language] if language else [],
            Jsonb({} if daily_max_runs is None else {"daily_max_runs": daily_max_runs}),
            Jsonb(
                {}
                if limit_per_provider is None
                else {"limit_per_provider": limit_per_provider}
            ),
        ),
    )
    stored = await load_collection_schedule(connection, source_key=source_key)
    if stored is None:  # pragma: no cover - Upsert 직후에는 항상 존재한다
        raise RuntimeError(f"수집 스케줄 저장에 실패했습니다: {source_key}")
    return stored


async def update_collection_schedule(
    connection: AsyncConnection[DictRow],
    *,
    source_key: str,
    schedule_cron: str | None = None,
    keywords: list[str] | None = None,
    language: str | None = None,
    limit_per_provider: int | None = None,
    daily_max_runs: int | None = None,
) -> GlobalCollectionSchedule | None:
    """등록된 수집 스케줄의 지정한 항목만 변경한다.

    None으로 넘긴 항목은 기존 값을 유지한다. jsonb 설정(쿼터·수집 수)은 통째로
    덮어쓰지 않고 병합해, 서로 다른 항목을 각각 바꿔도 값이 사라지지 않게 한다.

    Args:
        connection: Agent DB 연결
        source_key: 변경할 Source 식별 Key
        schedule_cron: 새 수집 주기 Cron 식
        keywords: 새 키워드 목록
        language: 새 검색 언어 힌트
        limit_per_provider: 새 수집 기사 수
        daily_max_runs: 새 일일 실행 한도

    Returns:
        변경된 스케줄 설정. source_key가 없으면 None
    """
    assignments: list[str] = []
    params: list[object] = []
    if schedule_cron is not None:
        assignments.append("schedule_cron = %s")
        params.append(schedule_cron)
    if keywords is not None:
        assignments.append("keywords = %s")
        params.append(keywords)
    if language is not None:
        assignments.append("languages = %s")
        params.append([language] if language else [])
    if limit_per_provider is not None:
        assignments.append("connector_config = connector_config || %s")
        params.append(Jsonb({"limit_per_provider": limit_per_provider}))
    if daily_max_runs is not None:
        assignments.append("quota_policy = quota_policy || %s")
        params.append(Jsonb({"daily_max_runs": daily_max_runs}))
    if not assignments:
        return await load_collection_schedule(connection, source_key=source_key)

    assignments.append("updated_at = clock_timestamp()")
    params.append(source_key)
    cursor = await connection.execute(
        f"""
        UPDATE agent.global_sources
        SET {", ".join(assignments)}
        WHERE source_key = %s
        RETURNING source_key
        """,
        tuple(params),
    )
    if await cursor.fetchone() is None:
        return None
    return await load_collection_schedule(connection, source_key=source_key)


async def set_collection_schedule_status(
    connection: AsyncConnection[DictRow], *, source_key: str, status: str
) -> GlobalCollectionSchedule | None:
    """수집 스케줄의 활성 상태를 바꾼다 (중지·재개).

    Args:
        connection: Agent DB 연결
        source_key: 상태를 바꿀 Source 식별 Key
        status: active 또는 paused

    Returns:
        변경된 스케줄 설정. source_key가 없으면 None

    Raises:
        ValueError: 허용하지 않는 status를 넘겼을 때
    """
    if status not in ("active", "paused"):
        raise ValueError("수집 스케줄 status는 active 또는 paused여야 합니다.")
    cursor = await connection.execute(
        """
        UPDATE agent.global_sources
        SET status = %s, updated_at = clock_timestamp()
        WHERE source_key = %s
        RETURNING source_key
        """,
        (status, source_key),
    )
    if await cursor.fetchone() is None:
        return None
    return await load_collection_schedule(connection, source_key=source_key)


async def load_collection_runs(
    connection: AsyncConnection[DictRow],
    *,
    source_key: str | None = None,
    limit: int = 20,
) -> list[GlobalCollectionRunRecord]:
    """수집 실행 이력을 최근 순으로 읽는다.

    Args:
        connection: Agent DB 연결
        source_key: 특정 Source만 볼 때 지정 (None이면 전체)
        limit: 최대 반환 건수 (1~200)

    Returns:
        started_at 내림차순 실행 이력 목록
    """
    if not 1 <= limit <= 200:
        raise ValueError("수집 이력 limit은 1에서 200 사이여야 합니다.")
    cursor = await connection.execute(
        """
        SELECT
            run.id,
            source.source_key,
            run.cursor_before ->> 'query' AS query,
            run.status,
            run.fetched_count,
            run.created_count,
            run.duplicate_count,
            run.failed_count,
            run.error_code,
            run.started_at,
            run.completed_at
        FROM agent.global_collection_runs AS run
        JOIN agent.global_sources AS source ON source.id = run.source_id
        WHERE %s::text IS NULL OR source.source_key = %s
        ORDER BY run.started_at DESC
        LIMIT %s
        """,
        (source_key, source_key, limit),
    )
    return [
        GlobalCollectionRunRecord(
            run_id=str(row["id"]),
            source_key=row["source_key"],
            query=row.get("query"),
            status=row["status"],
            fetched_count=int(row["fetched_count"]),
            created_count=int(row["created_count"]),
            duplicate_count=int(row["duplicate_count"]),
            failed_count=int(row["failed_count"]),
            error_code=row.get("error_code"),
            started_at=row["started_at"],
            completed_at=row.get("completed_at"),
        )
        for row in await cursor.fetchall()
    ]


async def persist_collected_articles(
    connection: AsyncConnection[DictRow],
    *,
    provider: str,
    query: str,
    articles: list[LatestArticle],
    content_status: str = "pending",
    source_key: str | None = None,
) -> dict[str, object]:
    """수집한 뉴스 기사 URL을 Global 수집 캐시에 중복 없이 저장한다.

    같은 Transaction에서 Global Source(DB-008)와 Collection Run(DB-009)을
    기록하고, URL 기준으로 아직 저장되지 않은 기사만 캐시 문서(DB-010)로
    새로 저장한다. 이미 있는 URL은 본문 수집 여부와 무관하게 건너뛴다.

    Args:
        connection: 시스템 Scope가 설정된 DB 연결
        provider: 수집 Provider 이름 (예: gdelt, naver)
        query: 이번 수집에 사용한 검색 키워드 문자열
        articles: Provider가 정규화한 최신 기사 목록
        content_status: 새로 저장한 문서의 초기 본문 상태 (기본 pending)
        source_key: 실행 이력을 귀속할 Source Key. 정기 수집은 실행을 지시한
            Source의 Key를 넘긴다. 생략하면 Provider 기본 Source에 기록한다

    Returns:
        source_id, run_id와 수집·생성·중복 건수, 저장된 문서 항목 목록
    """
    # 실행 이력은 "이 수집을 지시한 Source"에 남아야 한다. 예전에는 무조건
    # `latest-{provider}`에 기록해서, taxonomy 수집이 아무리 돌아도
    # `interest-taxonomy-google-news`의 마지막 실행 시각이 영영 비어 있었다.
    # 그러면 Scheduler는 그 Source를 "한 번도 안 돈 Source"로 보고 Cron 주기를
    # 건너뛰며(collection._evaluate_schedule), 일일 실행 한도도 0으로 세어
    # 아무 때도 걸리지 않는다. 즉 주기·쿼터 설정이 통째로 무력화된다.
    #
    # 이미 있는 Source는 updated_at만 건드린다. 표시명·주기·중지 여부는 Service가
    # 스케줄 API(SCH-017~020)로 정하는 값이라, 수집이 돌 때마다 덮어쓰면 중지해 둔
    # Source가 수동 실행 한 번에 되살아난다.
    resolved_source_key = source_key or f"latest-{provider}"
    source_cursor = await connection.execute(
        """
        INSERT INTO agent.global_sources (
            source_key,
            connector_type,
            display_name,
            status,
            connector_config
        ) VALUES (%s, %s, %s, 'active', %s)
        ON CONFLICT (source_key) DO UPDATE SET
            updated_at = clock_timestamp()
        RETURNING id
        """,
        (
            resolved_source_key,
            provider,
            f"Latest {provider}",
            Jsonb({"managed_by": "global-source-collector"}),
        ),
    )
    source = await source_cursor.fetchone()
    run_cursor = await connection.execute(
        """
        INSERT INTO agent.global_collection_runs (
            source_id,
            status,
            cursor_before
        ) VALUES (%s, 'running', %s)
        RETURNING id
        """,
        (source["id"], Jsonb({"query": query})),
    )
    run = await run_cursor.fetchone()

    created_count = 0
    duplicate_count = 0
    saved_items: list[dict[str, object]] = []
    for article in articles:
        url = article.url.strip()
        if not url:
            continue
        insert_cursor = await connection.execute(
            """
            INSERT INTO agent.global_source_documents (
                canonical_url,
                url_key,
                provider,
                search_query,
                source_name,
                language,
                title,
                description,
                content_status,
                published_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (canonical_url) DO NOTHING
            RETURNING id
            """,
            (
                url,
                _document_key(url),
                provider,
                query,
                article.source_name or None,
                article.language or "und",
                article.title,
                article.description or None,
                content_status,
                article.published_at,
            ),
        )
        head = await insert_cursor.fetchone()
        if head is None:
            # 이미 캐시에 있는 URL이므로 중복으로 센다.
            duplicate_count += 1
            continue
        created_count += 1
        saved_items.append(
            {
                "provider": provider,
                "title": article.title,
                "url": url,
                "document_id": str(head["id"]),
                "content_status": content_status,
                "published_at": (
                    article.published_at.isoformat()
                    if article.published_at
                    else None
                ),
                "source_name": article.source_name,
                "language": article.language,
            }
        )

    urls = [article.url.strip() for article in articles if article.url.strip()]
    if urls:
        await connection.execute(
            """
            INSERT INTO agent.global_source_document_topics (
                global_source_document_id, target_key, search_query
            )
            SELECT document.id, target.target_key, %s
            FROM agent.global_source_documents AS document
            JOIN agent.interest_collection_targets AS target
              ON lower(btrim(target.query)) = lower(btrim(%s))
             AND target.status = 'active'
            WHERE document.canonical_url = ANY(%s)
            ON CONFLICT (global_source_document_id, target_key) DO NOTHING
            """,
            (query, query, urls),
        )

    # 다음 수집 시각은 결과가 0건이어도 미룬다. 예전에는 URL이 하나라도 있을
    # 때만 갱신해서, 검색 결과가 없는 Topic은 next_collection_at이 과거에 멈춘 채
    # 계속 "수집할 차례"로 남았다. Scheduler tick(기본 60초)마다 같은 Topic을
    # 다시 검색하게 되어, 아무것도 못 찾는 주제일수록 외부 API를 가장 많이
    # 태우는 거꾸로 된 동작이 된다.
    await connection.execute(
        """
        UPDATE agent.interest_collection_targets
        SET
            last_collected_at = clock_timestamp(),
            next_collection_at = clock_timestamp()
                + make_interval(mins => refresh_interval_minutes)
        WHERE status = 'active'
          AND lower(btrim(query)) = lower(btrim(%s))
        """,
        (query,),
    )

    await connection.execute(
        """
        UPDATE agent.global_collection_runs
        SET
            status = 'completed',
            fetched_count = %s,
            created_count = %s,
            duplicate_count = %s,
            cursor_after = %s,
            completed_at = clock_timestamp()
        WHERE id = %s
        """,
        (
            len(articles),
            created_count,
            duplicate_count,
            Jsonb({"query": query}),
            run["id"],
        ),
    )
    return {
        "source_id": str(source["id"]),
        "run_id": str(run["id"]),
        "fetched_count": len(articles),
        "created_count": created_count,
        "duplicate_count": duplicate_count,
        "items": saved_items,
    }


async def claim_global_articles_for_fetch(
    connection: AsyncConnection[DictRow],
    *,
    limit: int,
) -> list[GlobalArticleToFetch]:
    """본문이 없는 캐시 문서(content_status='pending')를 점유해 반환한다.

    SKIP LOCKED로 pending 문서를 Batch 점유하고 즉시 `fetching` 상태로 바꿔
    다른 Worker가 같은 문서를 중복 수집하지 않게 한다.

    Args:
        connection: 시스템 Scope가 설정된 DB 연결
        limit: 한 번에 점유할 최대 문서 수

    Returns:
        본문을 채울 캐시 문서 ID와 URL 목록
    """
    if not 1 <= limit <= 100:
        raise ValueError("Global 기사 Claim limit은 1에서 100 사이여야 합니다.")
    cursor = await connection.execute(
        """
        WITH claimable AS (
            SELECT id
            FROM agent.global_source_documents
            WHERE content_status = 'pending'
            ORDER BY updated_at
            FOR UPDATE SKIP LOCKED
            LIMIT %s
        )
        UPDATE agent.global_source_documents AS document
        SET content_status = 'fetching'
        FROM claimable
        WHERE document.id = claimable.id
        RETURNING document.id, document.canonical_url, document.provider
        """,
        (limit,),
    )
    rows = await cursor.fetchall()
    return [
        GlobalArticleToFetch(
            document_id=str(row["id"]),
            url=row["canonical_url"],
            provider=row.get("provider") or "",
        )
        for row in rows
    ]


async def save_fetched_article_content(
    connection: AsyncConnection[DictRow],
    *,
    document_id: str,
    resolved_url: str,
    title: str,
    markdown: str,
    published_at: datetime | None,
) -> dict[str, object]:
    """Jina Reader가 수집한 본문을 캐시 문서에 채우고 fetched로 전환한다.

    수집 시점 발행일 메타가 이미 있으면 본문에서 파싱하지 못했더라도
    보존한다(COALESCE).

    Args:
        connection: 시스템 Scope가 설정된 DB 연결
        document_id: 본문을 채울 캐시 문서 ID
        resolved_url: Jina Reader가 리다이렉트까지 반영한 최종 URL
        title: 수집한 본문 제목
        markdown: 수집한 전체 본문 Markdown
        published_at: 본문에서 파싱한 게시 시각 (없으면 None)

    Returns:
        저장한 캐시 문서 ID와 전환된 상태
    """
    content_hash = compute_content_hash(markdown)
    cursor = await connection.execute(
        """
        UPDATE agent.global_source_documents
        SET
            -- 본문 수집기가 제목을 주지 않으면(YouTube 자막 등) 수집 때 저장한
            -- 제목을 그대로 둔다.
            title = COALESCE(%s, title),
            markdown = %s,
            content_hash = %s,
            resolved_url = %s,
            published_at = COALESCE(%s, published_at),
            content_status = 'fetched',
            fetched_at = clock_timestamp()
        WHERE id = %s
        RETURNING id
        """,
        (title, markdown, content_hash, resolved_url, published_at, document_id),
    )
    updated = await cursor.fetchone()
    if updated is None:
        raise RuntimeError(f"Global 캐시 문서를 찾을 수 없습니다: {document_id}")
    return {
        "document_id": str(updated["id"]),
        "content_status": "fetched",
    }


async def mark_global_article_fetch_failed(
    connection: AsyncConnection[DictRow],
    *,
    document_id: str,
    error_code: str,
    error_message: str,
) -> None:
    """본문 수집에 실패한 캐시 문서를 failed 상태로 표시한다.

    무한 재시도를 막기 위해 `content_status='failed'`로 전환하고 오류 원인을
    보존한다. 관리자가 원인을 확인한 뒤 pending으로 되돌려 재수집할 수 있다.
    """
    await connection.execute(
        """
        UPDATE agent.global_source_documents
        SET
            content_status = 'failed',
            fetch_error_code = %s,
            fetch_error_message = %s
        WHERE id = %s
        """,
        (error_code, error_message[:500], document_id),
    )


async def db_008(request: FeatureRequest) -> FeatureResult:
    """[DB-008] Global Source 저장.

    외부 수집 Source와 설정을 저장한다.
    """
    raise NotImplementedError("[DB-008] 기능 구현이 필요합니다.")


async def db_009(request: FeatureRequest) -> FeatureResult:
    """[DB-009] Global Collection Run 저장.

    수집 실행 결과와 상태를 저장한다.
    """
    raise NotImplementedError("[DB-009] 기능 구현이 필요합니다.")


async def db_010(request: FeatureRequest) -> FeatureResult:
    """[DB-010] Global 문서 저장.

    수집된 외부 문서를 수집 캐시에 저장한다.
    """
    raise NotImplementedError("[DB-010] 기능 구현이 필요합니다.")


async def db_011(request: FeatureRequest) -> FeatureResult:
    """[DB-011] Global Chunk 저장.

    Global Source 검색용 Chunk를 저장한다.
    """
    raise NotImplementedError("[DB-011] 기능 구현이 필요합니다.")


async def db_012(request: FeatureRequest) -> FeatureResult:
    """[DB-012] Global Embedding 저장.

    Global Source의 Vector 데이터를 저장한다.
    """
    raise NotImplementedError("[DB-012] 기능 구현이 필요합니다.")


async def db_013(request: FeatureRequest) -> FeatureResult:
    """[DB-013] Global Trend 저장.

    탐지된 트렌드와 문서 그룹을 저장한다.
    """
    raise NotImplementedError("[DB-013] 기능 구현이 필요합니다.")


async def db_014(request: FeatureRequest) -> FeatureResult:
    """[DB-014] Discovery Candidate 저장.

    생성 및 추천 후보를 저장한다.
    """
    raise NotImplementedError("[DB-014] 기능 구현이 필요합니다.")
