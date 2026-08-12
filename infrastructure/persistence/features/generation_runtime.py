"""사용자 Context, Report Builder Job·검색 Context와 생성 결과 영속화.

Service API의 생성 요청을 PostgreSQL Job으로 등록하고, Report Builder Worker가 개인
Wiki와 Global 문서를 검색해 만든 콘텐츠·Citation·Publish Snapshot을 저장한다.
"""

import hashlib
import json
import logging
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any, Sequence
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from agent.images.api import select_report_cover_image
from domain.interests.api import ActiveInterestRequiredError, int_012, int_013
from infrastructure.sources.connectors.api import (
    is_probable_content_image_url,
    resolve_article_image,
)
from infrastructure.persistence.features.interest_bundles import (
    ConnectionInterestBundleRepository,
)

logger = logging.getLogger(__name__)
from infrastructure.persistence.features.personal_wiki import set_personal_wiki_scope
from shared.report_models import ReportContextDocument, GeneratedReportContent
from shared.wiki_navigation_models import WikiNavigationPacket

type DictRow = dict[str, Any]


def _context_image_url(row: Mapping[str, Any]) -> str | None:
    """조회 Context의 대표 이미지를 본문 기준으로 재검증해 반환한다.

    Global 캐시는 저장된 Markdown에서 기사 이미지를 다시 계산하고, 다른
    Namespace는 배너·아이콘이 아닌 기존 HTTP(S) 이미지만 유지한다.
    """
    cached_url = str(row.get("image_url") or "").strip() or None
    if str(row.get("namespace_key") or "") == "global":
        return resolve_article_image(
            markdown=str(row.get("content") or ""),
            title=str(row.get("title") or ""),
            cached_url=cached_url,
        )
    if cached_url and is_probable_content_image_url(cached_url):
        return cached_url
    return None


class StaleContextVersionError(RuntimeError):
    """저장된 사용자 Context보다 오래되거나 같은 Version 요청 오류.

    현재 저장된 버전을 함께 담는다. Service는 자기 카운터로 버전을 매기는데 그
    카운터가 Agent와 독립이라, 한 번 어긋나면 무엇을 보내도 계속 거절된다.
    거절만 알려주면 Service가 맞출 방법이 없어 조회 API를 따로 만들거나 버전을
    임의로 점프시켜야 한다. 거절과 함께 현재 값을 주면 한 번의 왕복으로 수렴한다.

    (2026-08-06 실측: Service가 이 409를 "이미 최신"으로 삼켜, 온보딩 관심사가
    Agent로 전달되지 않는데도 아무도 알지 못했다.)
    """

    def __init__(self, user_id: str, *, current_context_version: int) -> None:
        """거절된 사용자와 현재 저장된 버전을 담는다."""
        super().__init__(user_id)
        self.user_id = user_id
        self.current_context_version = current_context_version


class UserContextRequiredError(RuntimeError):
    """Report Builder 생성에 필요한 사용자 Context가 없는 오류."""


@dataclass(frozen=True, slots=True)
class StoredUserContext:
    """PostgreSQL에 저장된 사용자 Context Snapshot."""

    context_id: str
    user_id: str
    context_version: int
    plan: str
    preferred_language: str
    personalization_enabled: bool
    interest_taxonomy_version: str | None
    selected_category_ids: list[str]
    selected_topic_ids: list[str]
    blocked_interest_ids: list[str]
    blocked_source_ids: list[str]
    signup_interests: list[dict[str, Any]]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PersistedGenerationSubmission:
    """Report Builder Generation Job과 생성 요청 저장 결과."""

    job_id: str
    generation_request_id: str


def _navigation_packet_snapshot(
    packets: Sequence[WikiNavigationPacket],
) -> dict[str, object]:
    """Reader가 읽은 Packet들을 Job Payload용 JSON 값으로 직렬화한다."""
    pages = []
    relations = []
    sources = []
    selected_versions: list[str] = []
    seen_pages: set[str] = set()
    seen_relations: set[str] = set()
    seen_sources: set[str] = set()
    for packet in packets:
        for page in packet.pages:
            if page.document_version_id in seen_pages:
                continue
            seen_pages.add(page.document_version_id)
            pages.append(
                {
                    "document_version_id": page.document_version_id,
                    "role": page.role,
                }
            )
            if page.role == "seed":
                selected_versions.append(page.document_version_id)
        for relation in packet.relations:
            if relation.relation_id in seen_relations:
                continue
            seen_relations.add(relation.relation_id)
            relations.append(
                {
                    "relation_id": relation.relation_id,
                    "source_document_id": relation.source_document_id,
                    "target_document_id": relation.target_document_id,
                    "relation_type": relation.relation_type,
                    "confidence": relation.confidence,
                    "provenance_kind": relation.provenance_kind,
                    "review_status": relation.review_status,
                    "rationale": relation.rationale,
                    "traversal_direction": relation.traversal_direction,
                    "hops": relation.hops,
                    "supports": [
                        {
                            "source_document_version_id": (
                                support.source_document_version_id
                            ),
                            "provenance_kind": support.provenance_kind,
                            "confidence": support.confidence,
                            "review_status": support.review_status,
                            "evidence": support.evidence,
                            "rationale": support.rationale,
                        }
                        for support in relation.supports
                    ],
                }
            )
        for source in packet.sources:
            source_key = (
                f"{source.wiki_document_version_id}:"
                f"{source.source_document_version_id}"
            )
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)
            sources.append(
                {
                    "wiki_document_version_id": source.wiki_document_version_id,
                    "source_document_id": source.source_document_id,
                    "source_document_version_id": source.source_document_version_id,
                    "source_type": source.source_type,
                    "title": source.title,
                    "url": source.url,
                    "relation_type": source.relation_type,
                    "saved_at": source.saved_at.isoformat(),
                    "saved_at_source": source.saved_at_source,
                    "stored_at": source.stored_at.isoformat(),
                    "published_at": (
                        source.published_at.isoformat()
                        if source.published_at is not None
                        else None
                    ),
                    "clipped_on": (
                        source.clipped_on.isoformat()
                        if source.clipped_on is not None
                        else None
                    ),
                }
            )
    latest = packets[-1]
    return {
        "query": latest.query,
        "wiki_version_id": latest.wiki_version_id,
        "selected_document_version_ids": selected_versions,
        "pages": pages,
        "relations": relations,
        "sources": sources,
        "budget": {"max_depth": 1, "max_pages": 6, "max_chunks": 12},
        "truncated": any(packet.truncated for packet in packets),
    }


async def persist_report_navigation_snapshot(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    job_id: str,
    topic: str,
    packets: Sequence[WikiNavigationPacket],
) -> None:
    """첫 Reader 선택·관계·Source를 Topic별 Job Payload에 고정한다."""
    if not packets:
        return
    snapshot = _navigation_packet_snapshot(packets)
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        cursor = await connection.execute(
            """
            UPDATE agent.agent_jobs
            SET payload = jsonb_set(
                    payload,
                    '{wiki_navigation_snapshots}',
                    COALESCE(payload -> 'wiki_navigation_snapshots', '{}'::jsonb)
                    || jsonb_build_object(%s::text, %s::jsonb),
                    true
                ),
                updated_at = clock_timestamp()
            WHERE id = %s
              AND user_id = %s
              AND job_type = 'report_generation'
            RETURNING id
            """,
            (topic, Jsonb(snapshot), job_id, user_id),
        )
        if await cursor.fetchone() is None:
            raise RuntimeError(
                f"Navigator Snapshot을 저장할 Report Job을 찾을 수 없습니다: {job_id}"
            )


def _pinned_wiki_snapshots(
    interest_bundle: Mapping[str, object] | None,
    *,
    root_limit: int = 2,
) -> list[tuple[str, Mapping[str, object]]]:
    """관심사 Bundle에서 루트 우선 Wiki Version Snapshot을 선택한다."""
    if not interest_bundle:
        return []
    root = interest_bundle.get("root")
    root_documents = root.get("documents") if isinstance(root, Mapping) else None
    selected: list[tuple[str, Mapping[str, object]]] = []
    seen_versions: set[str] = set()
    for raw in list(root_documents or [])[:root_limit]:
        if not isinstance(raw, Mapping):
            continue
        version_id = str(raw.get("document_version_id") or "").strip()
        if not version_id or version_id in seen_versions:
            continue
        seen_versions.add(version_id)
        selected.append(("wiki_root", raw))
    for neighbor in interest_bundle.get("neighbors") or []:
        if not isinstance(neighbor, Mapping):
            continue
        version_id = str(neighbor.get("document_version_id") or "").strip()
        if not version_id or version_id in seen_versions:
            continue
        seen_versions.add(version_id)
        selected.append(("wiki_neighbor", neighbor))
    return selected


async def load_pinned_wiki_context(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    interest_bundle: Mapping[str, object] | None,
    root_limit: int = 2,
) -> list[ReportContextDocument]:
    """Job에 고정된 Wiki Version을 점수와 무관하게 생성 Context로 조회한다.

    루트는 최대 두 Version, 이웃은 선택된 노드마다 한 Version을 읽는다. 각
    Version의 canonical summary에 Description·Definition Chunk 하나를 보강해,
    제목 재검색이 실패해도 사용자의 기존 지식이 생성기에 전달되게 한다.

    Args:
        connection: 개인 Wiki RLS Scope가 설정될 PostgreSQL 연결
        user_id: 조회 대상 사용자 ID
        interest_bundle: 접수 시 고정한 관심사 Bundle Payload
        root_limit: 포함할 최대 루트 Version 수

    Returns:
        루트 우선으로 정렬되고 P 참조가 붙은 Wiki Context 목록
    """
    if root_limit < 1:
        raise ValueError("고정 Wiki 루트 상한은 1 이상이어야 합니다.")
    snapshots = _pinned_wiki_snapshots(interest_bundle, root_limit=root_limit)
    if not snapshots:
        return []
    version_ids = [
        str(snapshot.get("document_version_id")) for _role, snapshot in snapshots
    ]
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        cursor = await connection.execute(
            """
            WITH requested AS (
                SELECT version_id, position
                FROM unnest(%s::uuid[]) WITH ORDINALITY
                    AS item(version_id, position)
            )
            SELECT
                version.id::text AS document_version_id,
                version.title,
                COALESCE(version.summary, '') AS summary,
                chunk.id::text AS chunk_id,
                COALESCE(chunk.content, '') AS content
            FROM requested
            JOIN agent.wiki_document_versions AS version
              ON version.id = requested.version_id
             AND version.namespace_key = %s
            JOIN agent.wiki_documents AS document
              ON document.id = version.document_id
             AND document.namespace_key = version.namespace_key
            LEFT JOIN LATERAL (
                SELECT candidate.id, candidate.content
                FROM agent.wiki_chunks AS candidate
                WHERE candidate.document_version_id = version.id
                  AND candidate.namespace_key = version.namespace_key
                  AND candidate.is_searchable
                ORDER BY
                    CASE
                        WHEN candidate.content LIKE '## Description%%' THEN 0
                        WHEN candidate.content LIKE '## Definition%%' THEN 0
                        ELSE 1
                    END,
                    candidate.chunk_index
                LIMIT 1
            ) AS chunk ON true
            WHERE document.document_kind IN ('entity', 'concept')
              AND document.deleted_at IS NULL
            ORDER BY requested.position
            """,
            (version_ids, f"user/{user_id}"),
        )
        rows = await cursor.fetchall()
    snapshot_by_version = {
        str(snapshot.get("document_version_id")): (role, snapshot)
        for role, snapshot in snapshots
    }
    contexts: list[ReportContextDocument] = []
    for row in rows:
        version_id = str(row["document_version_id"])
        role, snapshot = snapshot_by_version[version_id]
        summary = str(row.get("summary") or snapshot.get("summary") or "").strip()
        chunk = str(row.get("content") or "").strip()
        parts = [f"요약: {summary}" if summary else ""]
        if chunk and chunk not in summary:
            parts.append(chunk)
        content = "\n\n".join(part for part in parts if part)
        if not content:
            continue
        contexts.append(
            ReportContextDocument(
                reference=f"P{len(contexts) + 1}",
                document_version_id=version_id,
                chunk_id=str(row.get("chunk_id") or ""),
                namespace_key=f"user/{user_id}",
                title=str(row.get("title") or snapshot.get("keyword") or ""),
                content=content,
                url=None,
                score=1.0 if role == "wiki_root" else 0.95,
                context_role=role,
                source_updated_at=(
                    str(snapshot["updated_at"])
                    if snapshot.get("updated_at") is not None
                    else None
                ),
            )
        )
    return contexts


async def upsert_user_context_snapshot(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    context_version: int,
    plan: str,
    preferred_language: str,
    personalization_enabled: bool,
    interest_taxonomy_version: str | None,
    selected_category_ids: Sequence[str],
    selected_topic_ids: Sequence[str],
    blocked_interest_ids: Sequence[str],
    blocked_source_ids: Sequence[str],
    signup_interests: Sequence[dict[str, Any]] = (),
) -> StoredUserContext:
    """새로운 사용자 Context Version만 append-only Snapshot으로 저장한다.

    회원가입 시 선택한 관심 카테고리·토픽(`signup_interests`)은 파생 뷰인 관심사
    프로필이 아니라 사용자가 선언한 사실이므로, 버전 관리되는 이 Snapshot의
    `attributes.signup_interests`에 함께 보존한다.
    """
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"context/{user_id}",),
    )
    current_cursor = await connection.execute(
        """
        SELECT context_version
        FROM agent.user_context_snapshots
        WHERE user_id = %s AND deleted_at IS NULL
        ORDER BY context_version DESC
        LIMIT 1
        """,
        (user_id,),
    )
    current = await current_cursor.fetchone()
    if current is not None and context_version <= int(current["context_version"]):
        raise StaleContextVersionError(
            user_id, current_context_version=int(current["context_version"])
        )
    normalized_interests = [
        {
            "category": (
                str(item["category"]) if item.get("category") is not None else None
            ),
            "topics": list(item.get("topics", [])),
        }
        for item in signup_interests
    ]
    checksum_payload = {
        "context_version": context_version,
        "plan": plan,
        "preferred_language": preferred_language,
        "personalization_enabled": personalization_enabled,
        "interest_taxonomy_version": interest_taxonomy_version,
        "selected_category_ids": list(selected_category_ids),
        "selected_topic_ids": list(selected_topic_ids),
        "blocked_interest_ids": list(blocked_interest_ids),
        "blocked_source_ids": list(blocked_source_ids),
        "signup_interests": normalized_interests,
    }
    checksum = hashlib.sha256(
        json.dumps(checksum_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    cursor = await connection.execute(
        """
        INSERT INTO agent.user_context_snapshots (
            user_id,
            context_version,
            plan,
            preferred_language,
            personalization_enabled,
            interest_taxonomy_version,
            selected_category_ids,
            selected_topic_ids,
            blocked_interest_ids,
            blocked_source_ids,
            attributes,
            checksum
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, created_at
        """,
        (
            user_id,
            context_version,
            plan,
            preferred_language,
            personalization_enabled,
            interest_taxonomy_version,
            list(selected_category_ids),
            list(selected_topic_ids),
            list(blocked_interest_ids),
            list(blocked_source_ids),
            Jsonb({"signup_interests": normalized_interests}),
            checksum,
        ),
    )
    row = await cursor.fetchone()
    return StoredUserContext(
        context_id=str(row["id"]),
        user_id=user_id,
        context_version=context_version,
        plan=plan,
        preferred_language=preferred_language,
        personalization_enabled=personalization_enabled,
        interest_taxonomy_version=interest_taxonomy_version,
        selected_category_ids=list(selected_category_ids),
        selected_topic_ids=list(selected_topic_ids),
        blocked_interest_ids=list(blocked_interest_ids),
        blocked_source_ids=list(blocked_source_ids),
        signup_interests=normalized_interests,
        created_at=row["created_at"],
    )


async def _match_topic_interest_bundles(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    topics: Sequence[str],
) -> dict[str, dict[str, object]]:
    """주제마다 활성 관심사 일치 여부를 확인하고, 일치하면 범주 묶음을 스냅샷한다.

    SINGLE_TOPIC/topics 요청도 이미 사용자의 활성 관심사를 다루면 반응형 1홉
    검색 대신 INT-012 스냅샷 구조를 쓰게 한다(interest-bundle-report-design.md
    §9). Job 접수 시 고정해 Worker 재시도 중 관심 프로필이 바뀌어도 같은 Job은
    같은 근거로 재현되게 한다.

    매칭 이후 관심사가 비활성화되는 등 드문 경합으로 묶음 구성이 실패해도 이
    Job 등록 자체를 막지 않는다 — 그 주제만 기존 반응형 검색 경로로 남는다.
    """
    repository = ConnectionInterestBundleRepository(connection)
    bundles: dict[str, dict[str, object]] = {}
    seen: set[str] = set()
    for topic in topics:
        marker = topic.casefold()
        if not topic or marker in seen:
            continue
        seen.add(marker)
        interest_id = await int_013(repository, user_id, topic)
        if not interest_id:
            continue
        try:
            bundle = await int_012(
                repository, user_id, interest_id=interest_id, neighbor_limit=2
            )
        except ActiveInterestRequiredError:
            logger.warning(
                "주제-관심사 매칭 후 묶음 구성 실패, 반응형 검색으로 폴백한다: "
                "topic=%s interest_id=%s",
                topic,
                interest_id,
            )
            continue
        bundles[topic] = bundle.to_payload()
    return bundles


async def enqueue_report_generation_job(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    idempotency_key: str,
    topic: str | None,
    topics: list[str] | None = None,
    generation_scope: str = "SINGLE_TOPIC",
    interest_id: str | None = None,
    content_type: str,
    report_type: str = "",
    briefing_date: date | None = None,
    language: str | None,
    scheduled_at: datetime | None = None,
    request_id: str,
    change_history_enabled: bool = False,
    execution_mode: str = "sync",
    read_pipeline_version: str = "legacy_v1",
) -> PersistedGenerationSubmission:
    """최신 사용자 Context에 연결된 Report Builder Job과 생성 요청을 멱등 등록한다.

    scheduled_at을 지정하면 Worker Batch Claim의 `scheduled_at <= now`
    조건에 따라 그 시각 전에는 실행되지 않는 예약 Job으로 등록한다.
    같은 idempotency_key 재등록은 기존 Job을 재사용하며 예약 시각을
    변경하지 않는다.

    change_history_enabled는 Job Payload(jsonb)에만 싣는다. 서버가 사용자별로
    켬/끔 상태를 들고 있지 않고 요청마다 따라오는 값이라, 별도 컬럼이나 테이블
    변경 없이 실행 시점에 그대로 전달하면 된다.

    read_pipeline_version도 접수 시점 Payload에 고정한다. Worker 배포 설정이
    바뀌어도 이미 접수된 Job과 그 재시도는 같은 읽기 루프를 사용한다.
    """
    context_cursor = await connection.execute(
        """
        SELECT
            context.id,
            context.plan,
            context.preferred_language,
            (
                SELECT wiki.id::text
                FROM agent.wiki_versions AS wiki
                WHERE wiki.user_id = context.user_id
                  AND wiki.status = 'active'
                ORDER BY wiki.version DESC
                LIMIT 1
            ) AS wiki_version_id
        FROM agent.user_context_snapshots AS context
        WHERE context.user_id = %s AND context.deleted_at IS NULL
        ORDER BY context.context_version DESC
        LIMIT 1
        """,
        (user_id,),
    )
    context = await context_cursor.fetchone()
    if context is None:
        raise UserContextRequiredError(user_id)
    resolved_language = language or context["preferred_language"]
    interest_bundle: dict[str, object] | None = None
    topic_interest_bundles: dict[str, dict[str, object]] = {}
    resolved_topic = (topic or "").strip()
    resolved_topics = list(topics or [])
    if generation_scope == "INTEREST_BUNDLE":
        existing_bundle_cursor = await connection.execute(
            """
            SELECT
                job.id,
                generation_request.id AS generation_request_id
            FROM agent.agent_jobs AS job
            JOIN agent.generation_requests AS generation_request
              ON generation_request.job_id = job.id
            WHERE job.feature_id = 'SVC-008'
              AND COALESCE(job.user_id, '') = %s
              AND job.idempotency_key = %s
            """,
            (user_id, idempotency_key),
        )
        existing_bundle = await existing_bundle_cursor.fetchone()
        if existing_bundle is not None:
            return PersistedGenerationSubmission(
                job_id=str(existing_bundle["id"]),
                generation_request_id=str(
                    existing_bundle["generation_request_id"]
                ),
            )
        bundle = await int_012(
            ConnectionInterestBundleRepository(connection),
            user_id,
            interest_id=interest_id or "",
            neighbor_limit=2,
        )
        interest_bundle = bundle.to_payload()
        resolved_topic = bundle.root_keyword
        resolved_topics = []
    elif generation_scope != "SINGLE_TOPIC":
        raise ValueError(f"지원하지 않는 generation_scope입니다: {generation_scope}")
    else:
        topic_interest_bundles = await _match_topic_interest_bundles(
            connection,
            user_id=user_id,
            topics=[t for t in (resolved_topic, *resolved_topics) if t],
        )
    if not resolved_topic:
        raise ValueError("Report Builder 생성에는 topic이 필요합니다.")
    if execution_mode not in {"sync", "batch"}:
        raise ValueError(f"지원하지 않는 execution_mode입니다: {execution_mode}")
    if execution_mode == "batch" and change_history_enabled:
        raise ValueError("Batch Report는 변경점 추적을 지원하지 않습니다.")
    if execution_mode == "batch" and resolved_topics:
        raise ValueError("Batch Report는 다중 주제를 지원하지 않습니다.")
    if read_pipeline_version not in {"legacy_v1", "langgraph_v2"}:
        raise ValueError(
            f"지원하지 않는 Wiki 읽기 파이프라인 버전입니다: {read_pipeline_version}"
        )
    batch_contexts: list[dict[str, object]] = []
    if execution_mode == "batch":
        fixed_contexts = await load_report_context(
            connection,
            user_id=user_id,
            query=resolved_topic,
            top_k_per_scope=5,
        )
        if not fixed_contexts:
            raise ValueError("Batch Report에 고정할 Personal Wiki·Global Context가 없습니다.")
        batch_contexts = [asdict(item) for item in fixed_contexts]
    job_payload = {
        "topic": resolved_topic,
        # 여러 주제를 한 장에 묶는 요약 리포트용. 비어 있으면 topic 하나만 다룬다.
        "topics": resolved_topics,
        "generation_scope": generation_scope,
        "interest_id": interest_id,
        "interest_bundle": interest_bundle,
        # INT-013으로 활성 관심사와 매칭된 주제만 담는다. 없으면 빈 dict.
        "topic_interest_bundles": topic_interest_bundles,
        # 접수 시점의 Logical Index·Page Version 범위를 고정한다. None이면 Wiki가
        # 비어 있던 요청이며 Reader는 빈 Packet/Global 폴백으로 진행한다.
        "wiki_version_id": (
            str(context["wiki_version_id"])
            if context.get("wiki_version_id") is not None
            else None
        ),
        "read_pipeline_version": read_pipeline_version,
        "content_type": content_type,
        "report_type": report_type,
        # report_type 의미를 해석하지 않고, Service가 명시한 날짜가 있을 때만
        # REPORT-022 Snapshot 재사용을 시도한다. Worker는 주제 목록까지 일치해야
        # 이 값을 신뢰하고, 불일치·미준비 상태에서는 일반 조사로 폴백한다.
        "briefing_date": briefing_date.isoformat() if briefing_date else None,
        "language": resolved_language,
        "change_history_enabled": change_history_enabled,
        "execution_mode": execution_mode,
        "batch_contexts": batch_contexts,
    }
    job_cursor = await connection.execute(
        """
        INSERT INTO agent.agent_jobs (
            feature_id,
            job_type,
            user_id,
            idempotency_key,
            status,
            progress,
            payload,
            retryable,
            request_id,
            scheduled_at
        ) VALUES (
            'SVC-008', 'report_generation', %s, %s, 'queued', 0, %s, true, %s,
            COALESCE(%s, clock_timestamp())
        )
        ON CONFLICT (feature_id, COALESCE(user_id, ''), idempotency_key)
        DO NOTHING
        RETURNING id
        """,
        (user_id, idempotency_key, Jsonb(job_payload), request_id, scheduled_at),
    )
    job = await job_cursor.fetchone()
    if job is None:
        existing_cursor = await connection.execute(
            """
            SELECT id
            FROM agent.agent_jobs
            WHERE feature_id = 'SVC-008'
              AND COALESCE(user_id, '') = %s
              AND idempotency_key = %s
            """,
            (user_id, idempotency_key),
        )
        job = await existing_cursor.fetchone()
        if job is None:
            raise RuntimeError(f"멱등 충돌한 Report Builder Job을 찾을 수 없습니다: {idempotency_key}")
    request_cursor = await connection.execute(
        """
        INSERT INTO agent.generation_requests (
            job_id,
            user_id,
            user_context_snapshot_id,
            topic,
            content_type,
            plan,
            language,
            status,
            parameters
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s)
        ON CONFLICT (job_id) DO NOTHING
        RETURNING id
        """,
        (
            job["id"],
            user_id,
            context["id"],
            resolved_topic,
            content_type,
            context["plan"],
            resolved_language,
            # report_type은 Agent가 해석하지 않고 발행 시 그대로 돌려주기만
            # 하는 값이라, 전용 컬럼 대신 기존 parameters jsonb에 보관한다
            # (2026-08-06 이송우 협의: 값 정의는 Service가 소유).
            Jsonb(
                {
                    "retrieval": "personal-wiki-global-cache-keyword-v2",
                    "report_type": report_type,
                    "briefing_date": (
                        briefing_date.isoformat() if briefing_date else None
                    ),
                    "generation_scope": generation_scope,
                    "interest_id": interest_id,
                    "interest_bundle": interest_bundle,
                    "execution_mode": execution_mode,
                    # 발행 시 publish_payload로 그대로 흘려보내 Service가 본문
                    # 렌더링 규칙을 고를 수 있게 한다(이 키가 없으면 body가 어느
                    # 포맷인지 헤더 문자열을 추측해서 판별해야 한다).
                    "change_history_enabled": change_history_enabled,
                }
            ),
        ),
    )
    generation_request = await request_cursor.fetchone()
    if generation_request is None:
        existing_request_cursor = await connection.execute(
            "SELECT id FROM agent.generation_requests WHERE job_id = %s",
            (job["id"],),
        )
        generation_request = await existing_request_cursor.fetchone()
    return PersistedGenerationSubmission(
        job_id=str(job["id"]),
        generation_request_id=str(generation_request["id"]),
    )


def _embedding_vector_literal(query_embedding: Sequence[float]) -> str:
    """1536차원 Query Embedding을 안전한 pgvector Literal로 변환한다."""
    if len(query_embedding) != 1536:
        raise ValueError(
            f"개인 Wiki Query Embedding은 1536차원이어야 합니다: {len(query_embedding)}"
        )
    values: list[float] = []
    for raw_value in query_embedding:
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as error:
            raise ValueError("Query Embedding에 숫자가 아닌 값이 있습니다.") from error
        if not math.isfinite(value):
            raise ValueError("Query Embedding에는 유한한 숫자만 사용할 수 있습니다.")
        values.append(value)
    return "[" + ",".join(str(value) for value in values) + "]"


async def load_personal_wiki_vector_context(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    query_embedding: Sequence[float],
    model_name: str,
    top_k: int = 5,
) -> list[ReportContextDocument]:
    """활성 개인 Wiki Chunk를 Query Embedding과 Cosine 거리로 조회한다.

    현재 Entity·Concept Version과 같은 active Embedding config/model만 비교한다.
    유사도 hard cutoff는 적용하지 않고 top-k 후보를 반환해 Hybrid RRF가 Keyword
    결과와 함께 순서를 정하게 한다.

    Args:
        connection: 개인 Wiki RLS Scope가 설정된 PostgreSQL 연결
        user_id: 조회 대상 사용자 ID
        query_embedding: 1536차원 검색 Query Vector
        model_name: 저장 Vector와 일치시킬 Embedding 모델 이름
        top_k: 반환할 최대 개인 Wiki Chunk 수

    Returns:
        Cosine 거리 오름차순 개인 Wiki Context 목록
    """
    if not user_id.strip():
        raise ValueError("Vector 검색에 user_id가 필요합니다.")
    if not 1 <= top_k <= 20:
        raise ValueError("개인 Wiki Vector 검색 top_k는 1에서 20 사이여야 합니다.")
    vector_literal = _embedding_vector_literal(query_embedding)
    namespace_key = f"user/{user_id}"
    config_key = f"personal-wiki/{model_name}"
    cursor = await connection.execute(
        """
        WITH query_vector AS (
            SELECT %s::vector AS embedding
        ), ranked AS (
            SELECT
                version.id::text AS document_version_id,
                chunk.id::text AS chunk_id,
                document.namespace_key,
                version.title,
                chunk.content,
                COALESCE(
                    document.canonical_url,
                    version.source_metadata ->> 'url'
                ) AS url,
                version.created_at AS updated_at,
                wiki_embedding.embedding <=> query_vector.embedding AS distance
            FROM agent.wiki_embeddings AS wiki_embedding
            JOIN agent.embedding_configs AS config
              ON config.id = wiki_embedding.embedding_config_id
             AND config.status = 'active'
             AND config.config_key = %s
             AND config.model_name = %s
            JOIN agent.wiki_chunks AS chunk
              ON chunk.id = wiki_embedding.chunk_id
             AND chunk.namespace_key = wiki_embedding.namespace_key
             AND chunk.is_searchable
            JOIN agent.wiki_document_versions AS version
              ON version.id = chunk.document_version_id
             AND version.namespace_key = chunk.namespace_key
            JOIN agent.wiki_documents AS document
              ON document.id = version.document_id
             AND document.namespace_key = version.namespace_key
             AND document.current_version = version.version
            CROSS JOIN query_vector
            WHERE wiki_embedding.namespace_key = %s
              AND wiki_embedding.model_name = %s
              AND document.document_kind IN ('entity', 'concept')
              AND document.status = 'active'
              AND document.deleted_at IS NULL
            ORDER BY
                wiki_embedding.embedding <=> query_vector.embedding,
                chunk.id
            LIMIT %s
        )
        SELECT
            document_version_id,
            chunk_id,
            namespace_key,
            title,
            content,
            url,
            updated_at,
            (GREATEST(0.0, 1.0 - distance) + 0.05)::float8 AS score
        FROM ranked
        ORDER BY distance, chunk_id
        """,
        (
            vector_literal,
            config_key,
            model_name,
            namespace_key,
            model_name,
            top_k,
        ),
    )
    rows = await cursor.fetchall()
    return [
        ReportContextDocument(
            reference=f"P{index}",
            document_version_id=str(row["document_version_id"]),
            chunk_id=str(row["chunk_id"]),
            namespace_key=str(row["namespace_key"]),
            title=str(row["title"]),
            content=str(row["content"]),
            url=str(row["url"]) if row.get("url") else None,
            score=float(row["score"]),
            context_role="semantic_retrieval",
            source_updated_at=(
                str(row["updated_at"])
                if row.get("updated_at") is not None
                else None
            ),
        )
        for index, row in enumerate(rows, start=1)
    ]


async def load_report_context(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    query: str,
    top_k_per_scope: int = 5,
) -> list[ReportContextDocument]:
    """개인 Wiki와 Global 수집 캐시의 Keyword·Trigram 검색 Context를 조회한다.

    개인 Wiki는 `wiki_chunks`에서, Global 최신 자료는 수집 캐시
    (`global_source_documents`)에서 각각 검색해 Scope별 top-k로 합친다.
    캐시 문서는 Wiki Version·Chunk가 없으므로 참조 식별자를
    `gsrc:<캐시 문서 UUID>` 형태로 만들어 반환한다 — Citation 저장 시
    이 접두사로 캐시 출처를 구분한다.

    `document_kind = 'schema'` 문서는 제외한다. Wiki 목차 파일은 Namespace의
    모든 문서 제목을 담고 있어 어떤 검색어에도 걸리지만, 내용은 링크 목록뿐이라
    근거가 되지 못한다. 근거 자리를 차지하고 LLM이 링크 목록에서 사실을 지어낼
    여지도 남는다. (2026-08-05 실측: '반도체'·'코스피' 검색에서 0.126으로 통과해
    근거에 포함됐다.)

    본 검색이 한 건도 못 찾으면 최근 문서를 0점으로 채워 주는 폴백 질의가 있다.
    폴백에도 같은 제외 조건이 필요하다 — 오히려 목차 파일이 이 경로로 더 자주
    들어온다.

    **토픽 가산점(+1.0)은 검색어 글자가 아니라 수집 대상(Topic)으로 판정한다.**
    텍스트 점수만으로는 관련 문서와 잡음이 갈리지 않기 때문에(실측: 간격 0.01
    미만, retrieval-noise-measurement-2026-08-05.md) 이 가산점이 사실상 유일하게
    작동하는 관련성 신호다.

    그런데 사용자는 `우주·천문` 같은 **라벨**을 고르고, 수집은 `스페이스X`·`화성
    탐사` 같은 **확장 검색어**로 돌린다. 글자만 대조하면 확장 검색어로 모은 자료가
    전부 가산점을 못 받아, 정작 주제에 맞는 기사가 잡음과 같은 0.09 구간에 묻힌다.

    그래서 두 갈래로 본다.

      ① 이 검색어로 **직접** 수집한 문서        (`search_query` 일치)
      ② 같은 **수집 대상**에 묶인 문서          (`interest_collection_targets.query` 일치)

    ②가 라벨과 확장 검색어를 이어 준다. 수집이 어떤 검색어를 썼든 같은 Topic에
    연결돼 있으면 사용자가 고른 라벨로 찾을 수 있다.
    """
    if not 1 <= top_k_per_scope <= 20:
        raise ValueError("Report Builder 검색 top_k는 1에서 20 사이여야 합니다.")
    namespace_key = f"user/{user_id}"
    cursor = await connection.execute(
        """
        WITH personal AS (
            SELECT
                version.id::text AS document_version_id,
                chunk.id::text AS chunk_id,
                document.namespace_key,
                version.title,
                chunk.content,
                COALESCE(document.canonical_url, version.source_metadata->>'url') AS url,
                NULL::text AS image_url,
                version.created_at AS source_updated_at,
                GREATEST(
                    similarity(chunk.content, %s),
                    ts_rank(chunk.search_vector, plainto_tsquery('simple', %s))
                ) + 0.05 AS score
            FROM agent.wiki_chunks AS chunk
            JOIN agent.wiki_document_versions AS version
              ON version.id = chunk.document_version_id
             AND version.namespace_key = chunk.namespace_key
            JOIN agent.wiki_documents AS document
              ON document.id = version.document_id
             AND document.namespace_key = version.namespace_key
             AND document.current_version = version.version
            WHERE chunk.namespace_key = %s
              AND chunk.is_searchable
              AND document.deleted_at IS NULL
              AND document.document_kind <> 'schema'
              AND (
                    similarity(chunk.content, %s) > 0.05
                    OR chunk.search_vector @@ plainto_tsquery('simple', %s)
              )
        ), global_cache AS (
            SELECT
                'gsrc:' || cache.id AS document_version_id,
                'gsrc:' || cache.id AS chunk_id,
                'global' AS namespace_key,
                cache.title,
                cache.markdown AS content,
                COALESCE(cache.resolved_url, cache.canonical_url) AS url,
                cache.image_url,
                cache.updated_at AS source_updated_at,
                CASE WHEN topic_match.exact THEN 1.0 ELSE 0.0 END +
                GREATEST(
                    similarity(COALESCE(cache.search_body, cache.markdown), %s),
                    ts_rank(cache.search_vector, plainto_tsquery('simple', %s))
                ) AS score
            FROM agent.global_source_documents AS cache
            CROSS JOIN LATERAL (
                SELECT EXISTS (
                    SELECT 1
                    FROM agent.global_source_document_topics AS mapped
                    LEFT JOIN agent.interest_collection_targets AS target
                      ON target.target_key = mapped.target_key
                    WHERE mapped.global_source_document_id = cache.id
                      AND (
                            lower(btrim(mapped.search_query)) = lower(btrim(%s))
                            OR lower(btrim(target.query)) = lower(btrim(%s))
                      )
                ) AS exact
            ) AS topic_match
            WHERE cache.content_status = 'fetched'
              AND cache.markdown IS NOT NULL
              AND (
                    topic_match.exact
                    OR similarity(COALESCE(cache.search_body, cache.markdown), %s) > 0.05
                    OR cache.search_vector @@ plainto_tsquery('simple', %s)
              )
        ), scored AS (
            SELECT * FROM personal
            UNION ALL
            SELECT * FROM global_cache
        ), ranked AS (
            SELECT *, row_number() OVER (
                PARTITION BY namespace_key = 'global'
                ORDER BY score DESC, document_version_id, chunk_id
            ) AS scope_rank
            FROM scored
        )
        SELECT *
        FROM ranked
        WHERE scope_rank <= %s
        ORDER BY (namespace_key = 'global'), score DESC
        """,
        (
            query,  # 개인 Wiki trigram
            query,  # 개인 Wiki ts_rank
            namespace_key,
            query,  # 개인 Wiki WHERE trigram
            query,  # 개인 Wiki WHERE ts_query
            query,  # 풀 trigram
            query,  # 풀 ts_rank
            query,  # 토픽 일치 — 이 검색어로 직접 수집한 문서
            query,  # 토픽 일치 — 같은 수집 대상(Topic)에 묶인 문서
            query,  # 풀 WHERE trigram
            query,  # 풀 WHERE ts_query
            top_k_per_scope,
        ),
    )
    rows = await cursor.fetchall()
    if not rows:
        fallback_cursor = await connection.execute(
            """
            WITH personal AS (
                SELECT
                    version.id::text AS document_version_id,
                    chunk.id::text AS chunk_id,
                    document.namespace_key,
                    version.title,
                    chunk.content,
                    COALESCE(document.canonical_url, version.source_metadata->>'url') AS url,
                    NULL::text AS image_url,
                    0::float AS score,
                    document.updated_at AS recency,
                    chunk.chunk_index AS tiebreak
                FROM agent.wiki_chunks AS chunk
                JOIN agent.wiki_document_versions AS version
                  ON version.id = chunk.document_version_id
                 AND version.namespace_key = chunk.namespace_key
                JOIN agent.wiki_documents AS document
                  ON document.id = version.document_id
                 AND document.namespace_key = version.namespace_key
                 AND document.current_version = version.version
                WHERE chunk.namespace_key = %s
                  AND chunk.is_searchable
                  AND document.deleted_at IS NULL
                  AND document.document_kind <> 'schema'
            ), global_cache AS (
                SELECT
                    'gsrc:' || cache.id AS document_version_id,
                    'gsrc:' || cache.id AS chunk_id,
                    'global' AS namespace_key,
                    cache.title,
                    cache.markdown AS content,
                    COALESCE(cache.resolved_url, cache.canonical_url) AS url,
                    cache.image_url,
                    0::float AS score,
                    cache.updated_at AS recency,
                    0 AS tiebreak
                FROM agent.global_source_documents AS cache
                WHERE cache.content_status = 'fetched'
                  AND cache.markdown IS NOT NULL
            ), merged AS (
                SELECT * FROM personal
                UNION ALL
                SELECT * FROM global_cache
            ), recent AS (
                SELECT *, row_number() OVER (
                    PARTITION BY namespace_key = 'global'
                    ORDER BY recency DESC, tiebreak
                ) AS scope_rank
                FROM merged
            )
            SELECT
                document_version_id,
                chunk_id,
                namespace_key,
                title,
                content,
                url,
                image_url,
                score,
                recency AS source_updated_at
            FROM recent
            WHERE scope_rank <= %s
            ORDER BY (namespace_key = 'global'), scope_rank
            """,
            (namespace_key, top_k_per_scope),
        )
        rows = await fallback_cursor.fetchall()
    personal_index = 0
    global_index = 0
    contexts: list[ReportContextDocument] = []
    for row in rows:
        if row["namespace_key"] == "global":
            global_index += 1
            reference = f"G{global_index}"
        else:
            personal_index += 1
            reference = f"P{personal_index}"
        contexts.append(
            ReportContextDocument(
                reference=reference,
                document_version_id=str(row["document_version_id"]),
                chunk_id=str(row["chunk_id"]),
                namespace_key=row["namespace_key"],
                title=row["title"],
                content=row["content"],
                url=row["url"],
                image_url=_context_image_url(row),
                score=float(row["score"]),
                context_role=(
                    "global_retrieval"
                    if row["namespace_key"] == "global"
                    else "keyword_retrieval"
                ),
                source_updated_at=(
                    str(row["source_updated_at"])
                    if row.get("source_updated_at") is not None
                    else None
                ),
            )
        )
    return contexts


async def load_global_report_context(
    connection: AsyncConnection[DictRow],
    *,
    query: str,
    top_k: int = 5,
) -> list[ReportContextDocument]:
    """Global 수집 캐시만 Keyword·Trigram으로 검색한다.

    Reader Agent가 개인 Wiki는 Navigator로만 읽도록 개인 Wiki CTE를 포함하지
    않는다. 검색 결과가 없을 때도 개인 Wiki가 아니라 최신 Global 문서만 0점
    후보로 반환해 기존 풀 신선도·관련성 Gate가 폴백 여부를 결정하게 한다.

    Args:
        connection: 호출자가 Report Graph 전체에서 재사용하는 DB 연결
        query: Global 저장 자료에서 찾을 검색어
        top_k: 반환할 Global 문서 상한

    Returns:
        Global Namespace의 검색 Context 목록
    """
    if not query.strip():
        raise ValueError("Global 저장 자료 검색에 query가 필요합니다.")
    if not 1 <= top_k <= 20:
        raise ValueError("Global 저장 자료 검색 top_k는 1에서 20 사이여야 합니다.")
    cursor = await connection.execute(
        """
        WITH scored AS (
            SELECT
                'gsrc:' || cache.id AS document_version_id,
                'gsrc:' || cache.id AS chunk_id,
                'global' AS namespace_key,
                cache.title,
                cache.markdown AS content,
                COALESCE(cache.resolved_url, cache.canonical_url) AS url,
                cache.image_url,
                cache.updated_at AS source_updated_at,
                CASE WHEN topic_match.exact THEN 1.0 ELSE 0.0 END +
                GREATEST(
                    similarity(COALESCE(cache.search_body, cache.markdown), %s),
                    ts_rank(cache.search_vector, plainto_tsquery('simple', %s))
                ) AS score
            FROM agent.global_source_documents AS cache
            CROSS JOIN LATERAL (
                SELECT EXISTS (
                    SELECT 1
                    FROM agent.global_source_document_topics AS mapped
                    LEFT JOIN agent.interest_collection_targets AS target
                      ON target.target_key = mapped.target_key
                    WHERE mapped.global_source_document_id = cache.id
                      AND (
                            lower(btrim(mapped.search_query)) = lower(btrim(%s))
                            OR lower(btrim(target.query)) = lower(btrim(%s))
                      )
                ) AS exact
            ) AS topic_match
            WHERE cache.content_status = 'fetched'
              AND cache.markdown IS NOT NULL
              AND (
                    topic_match.exact
                    OR similarity(COALESCE(cache.search_body, cache.markdown), %s) > 0.05
                    OR cache.search_vector @@ plainto_tsquery('simple', %s)
              )
        )
        SELECT *
        FROM scored
        ORDER BY score DESC, document_version_id
        LIMIT %s
        """,
        (query, query, query, query, query, query, top_k),
    )
    rows = await cursor.fetchall()
    if not rows:
        fallback_cursor = await connection.execute(
            """
            SELECT
                'gsrc:' || cache.id AS document_version_id,
                'gsrc:' || cache.id AS chunk_id,
                'global' AS namespace_key,
                cache.title,
                cache.markdown AS content,
                COALESCE(cache.resolved_url, cache.canonical_url) AS url,
                cache.image_url,
                cache.updated_at AS source_updated_at,
                0::float AS score
            FROM agent.global_source_documents AS cache
            WHERE cache.content_status = 'fetched'
              AND cache.markdown IS NOT NULL
            ORDER BY cache.updated_at DESC, cache.id
            LIMIT %s
            """,
            (top_k,),
        )
        rows = await fallback_cursor.fetchall()
    return [
        ReportContextDocument(
            reference=f"G{index}",
            document_version_id=str(row["document_version_id"]),
            chunk_id=str(row["chunk_id"]),
            namespace_key="global",
            title=str(row["title"]),
            content=str(row["content"]),
            url=str(row["url"]) if row.get("url") else None,
            image_url=_context_image_url(row),
            score=float(row["score"]),
            context_role="global_retrieval",
            source_updated_at=(
                str(row["source_updated_at"])
                if row.get("source_updated_at") is not None
                else None
            ),
        )
        for index, row in enumerate(rows, start=1)
    ]


def _uuid_or_none(value: str) -> str | None:
    """UUID 형식이 아닌 문서 식별자를 None으로 바꾼다.

    실시간 외부 자료(live_sources)는 Wiki 문서가 아니라서 Version·Chunk UUID가
    없고 참조 ID(L1 등)를 대신 담는다. Global 수집 캐시 문서도 `gsrc:` 접두사
    식별자를 담는다. citations의 Wiki uuid 컬럼·FK에 그대로 넣으면 저장이
    실패하므로 여기서는 None으로 바꾸고, 캐시 출처는 별도 컬럼
    (global_source_document_id)이, 실시간 자료는 URL이 증빙을 맡는다.
    """
    if not value:
        return None
    try:
        UUID(value)
    except ValueError:
        return None
    return value


# Global 수집 캐시 문서를 가리키는 검색 Context 식별자 접두사.
_GLOBAL_CACHE_PREFIX = "gsrc:"


def _global_cache_id_or_none(value: str) -> str | None:
    """'gsrc:<uuid>' 형태의 Global 캐시 참조에서 캐시 문서 UUID를 꺼낸다.

    Wiki 문서 UUID·실시간 참조(L1 등)는 None을 반환해 citations의
    global_source_document_id FK에 잘못 저장되지 않게 한다.
    """
    if not value or not value.startswith(_GLOBAL_CACHE_PREFIX):
        return None
    candidate = value[len(_GLOBAL_CACHE_PREFIX):]
    try:
        UUID(candidate)
    except ValueError:
        return None
    return candidate


# 카드 하나가 주장할 수 있는 taxonomy Topic 수 상한. content_tags(5)와 같은 기준이다 —
# 상한이 없으면 인용을 많이 단 리포트가 Topic 열댓 개를 달고 나가서, Service의 관심사
# 교집합 매칭이 사실상 "아무 카드나 걸린다"가 된다.
_MAX_TAXONOMY_TOPIC_IDS = 5


async def _derive_taxonomy_topics(
    connection: AsyncConnection[DictRow],
    *,
    candidate_id: str,
    fallback_topics: Sequence[str],
) -> tuple[str, list[str]]:
    """이 리포트가 매핑되는 taxonomy Topic을 결정론으로 고른다 (2026-08-11 계약).

    Service는 이 값으로 "뷰어 관심사 ∩ 카드 Topic"을 계산해 추천 피드를 만든다.
    카드에는 자유 문자열 태그밖에 없어서 공통 식별자가 없었고, 그 자리를 메운다.

    **LLM을 쓰지 않는다.** 두 갈래 모두 이미 있는 매핑을 거슬러 올라가는 결정적
    파생이라 추가 비용·지연이 없다(2026-08-11 우석·영현·여진 합의로 채택한 이유).

    ① 인용 원본 파생 — 이 리포트가 **실제로 인용한** Global 수집 문서가 어느
       수집 대상(Topic)에서 왔는지 거슬러 올라간다. 요청 주제가 아니라 근거를
       보므로, 요청과 실제 내용이 갈려도 따라간다(tags/content_tags를 분리한
       것과 같은 이유).
    ② ①이 비면 요청 주제 이름으로 taxonomy를 찾는다. 개인 Wiki만 인용한
       리포트가 여기 해당한다 — 개인 Wiki 청크에는 수집 대상이 없다.

    ``custom:{해시}`` 수집 대상(직접 입력·Wiki 자동 등록 주제)은 애초에 topic_id가
    없어서 ``target_type = 'taxonomy'`` 조건에 자연히 걸러진다.

    Returns:
        (taxonomy_version, topic_ids). **못 찾으면 ("", [])** 이고 예외를 던지지
        않는다 — 검색·추천 보조 정보라, 이것 때문에 발행이 멈추면 안 된다
        (content_tags와 같은 원칙).
    """
    cursor = await connection.execute(
        """
        SELECT
            target.taxonomy_version,
            target.topic_id,
            min(citation.ordinal) AS first_ordinal,
            count(*) AS hits
        FROM agent.citations AS citation
        JOIN agent.global_source_document_topics AS mapped
          ON mapped.global_source_document_id = citation.global_source_document_id
        JOIN agent.interest_collection_targets AS target
          ON target.target_key = mapped.target_key
        WHERE citation.candidate_id = %s
          AND citation.global_source_document_id IS NOT NULL
          AND target.target_type = 'taxonomy'
        GROUP BY target.taxonomy_version, target.topic_id
        ORDER BY first_ordinal, hits DESC, target.topic_id
        """,
        (candidate_id,),
    )
    rows = await cursor.fetchall()
    if not rows:
        rows = await _taxonomy_topics_by_name(connection, fallback_topics)
    return _pick_single_taxonomy_version(rows)


# 정식 이름을 조각으로 쪼갤 때 쓰는 구분자. 카탈로그 이름이 "AI·머신러닝"처럼
# 가운뎃점으로 두 갈래를 묶는 형태라, 사용자는 그중 한쪽만 적는 일이 잦다.
_TAXONOMY_NAME_SEPARATORS = "·/,"

# 맞춰 보는 순서. 앞쪽이 더 정확해서, 한 주제가 여러 갈래로 걸리면 앞쪽을 쓴다.
_MATCH_NAME = 0
_MATCH_KEYWORD = 1
_MATCH_NAME_TOKEN = 2


def _normalize_topic_name(value: object) -> str:
    """이름 비교용 정규화 — 앞뒤 공백 제거 + 대소문자 무시("ai" = "AI")."""
    return str(value).strip().casefold()


async def _taxonomy_topics_by_name(
    connection: AsyncConnection[DictRow],
    topics: Sequence[str],
) -> list[DictRow]:
    """요청 주제 이름을 taxonomy 카탈로그와 맞춰 본다 (파생 ②).

    **세 갈래를 순서대로 본다. 전부 완전 일치이며 부분 문자열·유사도는 쓰지 않는다.**

    1. 정식 이름 — ``AI·머신러닝``
    2. ``keywords`` 항목 — ``반도체`` → ``industry``
    3. 정식 이름을 구분자로 쪼갠 조각 — ``AI·머신러닝`` → ``AI``, ``머신러닝``

    2·3이 필요한 이유(2026-08-11 리허설): 요청 주제는 사용자가 적은 관심사 이름이라
    카탈로그 정식 이름과 잘 안 맞는다. 실측 ``[AI, 경제, 반도체]`` 가 1단계로는 0건이었다 —
    ``AI`` 는 ``AI·머신러닝`` 의 앞 조각이고, ``반도체`` 는 이름이 아니라 ``industry`` 의
    keywords 항목이다. 온보딩에서 taxonomy 를 고른 사용자는 정식 이름이 그대로 와서
    1단계로 맞지만, 자유 입력 관심사는 그렇지 않다.

    **한 조각이 여러 Topic 에 걸리면 그 조각은 버린다** (2026-08-11 우석 안전핀).
    모호할 때 안 붙이는 쪽이 엉뚱하게 붙는 것보다 낫고, 그래야 규칙이 결정적으로 남는다.
    모호 판정은 **같은 taxonomy 버전 안에서** 한다 — 버전이 다른 같은 이름은 충돌이 아니다.

    카탈로그는 44행짜리라 통째로 읽어 파이썬에서 맞춘다. SQL 로 세 갈래를 표현하면
    정규화가 양쪽으로 갈라져(``lower(btrim())`` vs 파이썬) 오히려 안 맞는 값이 생긴다.
    """
    needles = [_normalize_topic_name(topic) for topic in topics if str(topic).strip()]
    if not needles:
        return []
    cursor = await connection.execute(
        """
        SELECT taxonomy_version, topic_id, name, keywords
        FROM agent.interest_taxonomy_topics
        """
    )
    catalog = await cursor.fetchall()
    if not catalog:
        return []

    # (버전, 갈래, 찾을 말) -> 걸린 topic_id 집합. 집합이 2개 이상이면 모호해서 버린다.
    index: dict[tuple[str, int, str], set[str]] = {}

    def remember(version: str, kind: int, needle: str, topic_id: str) -> None:
        if needle:
            index.setdefault((version, kind, needle), set()).add(topic_id)

    for row in catalog:
        version = str(row["taxonomy_version"])
        topic_id = str(row["topic_id"])
        name = str(row["name"])
        remember(version, _MATCH_NAME, _normalize_topic_name(name), topic_id)
        for keyword in row["keywords"] or []:
            remember(version, _MATCH_KEYWORD, _normalize_topic_name(keyword), topic_id)
        for token in _split_taxonomy_name(name):
            remember(version, _MATCH_NAME_TOKEN, token, topic_id)

    versions = {str(row["taxonomy_version"]) for row in catalog}
    matched: list[DictRow] = []
    for ordinal, needle in enumerate(needles):
        for version in sorted(versions):
            for kind in (_MATCH_NAME, _MATCH_KEYWORD, _MATCH_NAME_TOKEN):
                topic_ids = index.get((version, kind, needle))
                if not topic_ids:
                    continue
                if len(topic_ids) > 1:
                    # 모호한 말 — 이 갈래는 버리고 더 느슨한 갈래도 보지 않는다.
                    break
                matched.append(
                    {
                        "taxonomy_version": version,
                        "topic_id": next(iter(topic_ids)),
                        "first_ordinal": ordinal,
                        "hits": 1,
                    }
                )
                break
    return matched


def _split_taxonomy_name(name: str) -> list[str]:
    """정식 이름을 구분자로 쪼갠 조각들 — 이름 자체와 같은 한 조각은 뺀다."""
    separated = name
    for separator in _TAXONOMY_NAME_SEPARATORS:
        separated = separated.replace(separator, "\n")
    tokens = [_normalize_topic_name(part) for part in separated.split("\n")]
    tokens = [token for token in tokens if token]
    if len(tokens) < 2:
        return []   # 쪼갤 게 없으면 1단계(정식 이름)와 같은 말이라 중복이다
    return tokens


def _pick_single_taxonomy_version(rows: Sequence[DictRow]) -> tuple[str, list[str]]:
    """한 버전의 Topic만 남긴다 — 버전과 id가 따로 노는 값을 안 내보내려고.

    taxonomy 버전이 올라간 직후에는 옛 버전 수집 대상과 새 버전이 잠시 섞인다.
    그때 두 버전의 topic_id를 한 배열에 담아 보내면, 받는 쪽은 어느 버전 카탈로그로
    풀어야 할지 알 수 없다. 매칭이 가장 많은 버전만 남긴다.

    동수일 때는 버전 문자열이 큰 쪽으로 가른다 — semver 비교가 아니라 **결과를
    한쪽으로 고정하기 위한 결정적 규칙**일 뿐이다(같은 입력이 실행할 때마다 다른
    버전을 고르면 카드마다 기준이 흔들린다). 버전이 섞이는 구간 자체가 카탈로그
    교체 직후 잠깐이라 이 이상 정교하게 갈 이유가 없다.
    """
    if not rows:
        return "", []
    hits_by_version: dict[str, int] = {}
    for row in rows:
        version = str(row["taxonomy_version"])
        hits_by_version[version] = hits_by_version.get(version, 0) + int(row["hits"])
    winner = max(hits_by_version.items(), key=lambda item: (item[1], item[0]))[0]
    topic_ids: list[str] = []
    for row in rows:
        if str(row["taxonomy_version"]) != winner:
            continue
        topic_id = str(row["topic_id"])
        if topic_id in topic_ids:
            continue
        topic_ids.append(topic_id)
        if len(topic_ids) >= _MAX_TAXONOMY_TOPIC_IDS:
            break
    return winner, topic_ids


def _requested_topic_names(
    generation_request: DictRow, topic: str
) -> list[str]:
    """파생 ②에 넣을 요청 주제 이름 — 아침은 topics[], 나머지는 topic.

    아침 브리핑의 ``generation_requests.topic``은 카드 제목용 고정 문구다. 실제
    주제는 Job payload의 ``topics``에 있고, 그 행은 멱등키 때문에 이미 JOIN돼 있다.
    깊게 파기(INTEREST_BUNDLE)는 둘 다 없어서 빈 목록이 된다 — 파생 ①만 쓴다.
    """
    payload = generation_request.get("job_payload") or {}
    raw_topics = payload.get("topics") if isinstance(payload, dict) else None
    names = [str(name) for name in raw_topics if str(name).strip()] if raw_topics else []
    if names:
        return names
    return [topic] if topic else []


async def persist_report_generation(
    connection: AsyncConnection[DictRow],
    *,
    job_id: str,
    user_id: str,
    attempt_number: int,
    content_type: str,
    generated: GeneratedReportContent,
    contexts: Sequence[ReportContextDocument],
    latency_ms: int,
    review_outcome: str = "",
    review_problem: str = "",
    change_history_used: bool = False,
) -> dict[str, object]:
    """생성 Run·후보·Citation·Publish Snapshot·Outbox를 한 트랜잭션에 저장한다.

    review_outcome은 검토자(critic)가 이 리포트에 내린 최종 판정이다. 발행된
    결과물만 봐서는 "검토를 통과했다"와 "검토가 실패해 그냥 나갔다"를 구분할 수
    없어서 함께 남긴다 — 검토자는 실패해도 발행을 막지 않기 때문이다
    (2026-08-05 실측: 인용이 엉뚱한 리포트가 발행됐는데 검토자가 돌았는지조차
    로그 없이는 알 수 없었다).

    change_history_used는 **요청이 토글을 켰는지가 아니라, 델타 경로가 실제로
    이 본문을 만들었는지**다. 호출자(agent/graph.py의 persist 노드)가
    change_history 노드의 성공 여부로 판단해 넘긴다. 요청 파라미터를 그대로
    읽으면 서버 차단 스위치(CHANGE_HISTORY_ENABLED=0)나 델타 경로 자체 실패로
    기존 generate() 본문이 나갔을 때도 값이 true로 남아 body 구조와 어긋난다
    (2026-08-11 풀스택 피드백).
    """
    # 요청 멱등키는 Job 행이 원문 그대로 갖고 있으므로 여기서 함께 읽는다
    # (2026-08-06 협의: Service가 generation_pendings와 완료 카드를 잇는 열쇠).
    # generation_requests.parameters에 따로 복사해 두지 않는 이유는, 그렇게 하면
    # 이 변경 이전에 등록된 Job이 영영 빈 값으로 남기 때문이다. 조인해서 읽으면
    # 이미 큐에 들어가 있는 Job도 그대로 키가 실린다.
    request_cursor = await connection.execute(
        """
        SELECT
            generation_request.id,
            generation_request.topic,
            generation_request.parameters,
            job.idempotency_key AS request_idempotency_key,
            -- taxonomy Topic 파생 ②가 쓴다. 아침 브리핑은 generation_request.topic이
            -- 카드 제목용 고정 문구라, 실제 주제는 이 payload의 topics에만 있다.
            job.payload AS job_payload
        FROM agent.generation_requests AS generation_request
        JOIN agent.agent_jobs AS job
          ON job.id = generation_request.job_id
        WHERE generation_request.job_id = %s AND generation_request.user_id = %s
        FOR UPDATE OF generation_request
        """,
        (job_id, user_id),
    )
    generation_request = await request_cursor.fetchone()
    if generation_request is None:
        raise ValueError("Report Builder Job에 연결된 generation_request가 없습니다.")
    await connection.execute(
        "UPDATE agent.generation_requests SET status = 'running', updated_at = clock_timestamp() WHERE id = %s",
        (generation_request["id"],),
    )
    run_cursor = await connection.execute(
        """
        INSERT INTO agent.generation_runs (
            generation_request_id,
            user_id,
            attempt_number,
            status,
            latency_ms,
            run_metadata
        ) VALUES (%s, %s, %s, 'running', %s, %s)
        RETURNING id
        """,
        (
            generation_request["id"],
            user_id,
            attempt_number,
            latency_ms,
            Jsonb(
                {
                    "retrieval_references": [context.reference for context in contexts],
                    "retrieval_scores": {
                        context.reference: context.score for context in contexts
                    },
                    "retrieval_contexts": [
                        {
                            "reference": context.reference,
                            "namespace_key": context.namespace_key,
                            "context_role": context.context_role,
                            "source_updated_at": context.source_updated_at,
                        }
                        for context in contexts
                    ],
                    "review_outcome": review_outcome,
                    "review_problem": review_problem,
                }
            ),
        ),
    )
    generation_run = await run_cursor.fetchone()
    content_id = f"report-{job_id}"
    version_cursor = await connection.execute(
        """
        SELECT COALESCE(MAX(version), 0) + 1 AS next_version
        FROM agent.generated_content_candidates
        WHERE content_id = %s
        """,
        (content_id,),
    )
    version_row = await version_cursor.fetchone()
    content_version = int(version_row["next_version"])
    selected_cover = select_report_cover_image(
        assets=[
            {
                "reference": context.reference,
                "namespace_key": context.namespace_key,
                "image_url": context.image_url,
                "source_url": context.url,
                "source_title": context.title,
            }
            for context in contexts
        ],
        citation_references=generated.citation_references,
        body=generated.body,
    )
    cover_image_payload = selected_cover.to_payload() if selected_cover else None
    snapshot_hash = hashlib.sha256(
        (
            f"{generated.title}\n{generated.summary}\n{generated.body}\n"
            f"{json.dumps(cover_image_payload, ensure_ascii=False, sort_keys=True)}"
        ).encode("utf-8")
    ).hexdigest()
    await connection.execute(
        """
        UPDATE agent.generated_content_candidates
        SET status = 'superseded', updated_at = clock_timestamp()
        WHERE content_id = %s AND status IN ('draft', 'ready')
        """,
        (content_id,),
    )
    candidate_cursor = await connection.execute(
        """
        INSERT INTO agent.generated_content_candidates (
            generation_request_id,
            generation_run_id,
            user_id,
            content_id,
            version,
            content_type,
            status,
            title,
            summary,
            body,
            structured_body,
            snapshot_hash
        ) VALUES (%s, %s, %s, %s, %s, %s, 'ready', %s, %s, %s, %s, %s)
        RETURNING id, created_at
        """,
        (
            generation_request["id"],
            generation_run["id"],
            user_id,
            content_id,
            content_version,
            content_type,
            generated.title,
            generated.summary,
            generated.body,
            Jsonb({"format": "markdown"}),
            snapshot_hash,
        ),
    )
    candidate = await candidate_cursor.fetchone()
    contexts_by_reference = {context.reference: context for context in contexts}
    citation_payloads: list[dict[str, object]] = []
    for ordinal, reference in enumerate(generated.citation_references):
        context = contexts_by_reference[reference]
        citation_hash = hashlib.sha256(
            f"{candidate['id']}:{reference}:{context.chunk_id}".encode("utf-8")
        ).hexdigest()
        citation_cursor = await connection.execute(
            """
            INSERT INTO agent.citations (
                candidate_id,
                user_id,
                ordinal,
                document_version_id,
                chunk_id,
                global_source_document_id,
                title,
                url,
                quoted_text,
                claim_paths,
                citation_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                candidate["id"],
                user_id,
                ordinal,
                _uuid_or_none(context.document_version_id),
                _uuid_or_none(context.chunk_id),
                _global_cache_id_or_none(context.document_version_id),
                context.title,
                context.url,
                context.content[:500],
                [reference],
                citation_hash,
            ),
        )
        citation = await citation_cursor.fetchone()
        citation_payloads.append(
            {
                "citation_id": str(citation["id"]),
                "title": context.title,
                "url": context.url or "",
                "reference": reference,
            }
        )
    await connection.execute(
        """
        UPDATE agent.generation_runs
        SET status = 'completed', completed_at = clock_timestamp()
        WHERE id = %s
        """,
        (generation_run["id"],),
    )
    await connection.execute(
        """
        UPDATE agent.generation_requests
        SET status = 'completed', updated_at = clock_timestamp()
        WHERE id = %s
        """,
        (generation_request["id"],),
    )
    # 카드 관심사 태그(service.card_interest_tags)의 원천이다. 리포트 1건은
    # topic 1개로 생성되므로 항상 원소 1개짜리 목록이다. service 워커는 받은
    # 문자열을 그대로 저장·노출하므로 빈 문자열은 빈 태그로 보이게 된다.
    topic = str(generation_request["topic"] or "").strip()
    # 요청에서 받은 그대로 돌려준다. Service는 요청과 Claim 시점이 떨어져 있어
    # 이 값이 없으면 카드가 어떤 맥락에서 만들어졌는지 다시 짜맞춰야 한다
    # (2026-08-06 이송우 협의). Agent는 해석하지 않는다.
    parameters = generation_request.get("parameters") or {}
    report_type = str(parameters.get("report_type") or "")
    # 요청 멱등키도 같은 이유로 원문 그대로 싣는다. report_type이 "어떤 맥락에서
    # 만들어졌나"를 알려준다면, 이 값은 "어느 요청의 결과인가"를 특정한다 —
    # Service는 이것으로 대기 행(generation_pendings)을 완료로 전환한다.
    request_idempotency_key = str(
        generation_request.get("request_idempotency_key") or ""
    )
    generation_scope = str(parameters.get("generation_scope") or "SINGLE_TOPIC")
    # 요청 파라미터가 아니라 호출자가 넘긴 실제 실행 결과를 싣는다 — 서버 차단
    # 스위치나 델타 경로 실패로 body가 기존 형식으로 나갔는데 값만 true로 남는
    # 것을 막기 위해서다. Service가 이 값으로 본문이 "이번에 달라진 점" 폼인지
    # 기존 폼인지 구분해 렌더링 규칙을 고를 수 있게 한다 — 헤더 문자열을 파싱해
    # 추측하게 하면 안 된다.
    change_history_enabled = change_history_used
    source_interest_id = str(parameters.get("interest_id") or "")
    raw_interest_bundle = parameters.get("interest_bundle")
    interest_bundle = (
        raw_interest_bundle if isinstance(raw_interest_bundle, dict) else {}
    )
    interest_profile_id = str(interest_bundle.get("profile_id") or "")
    bundle_keywords = [
        str(keyword).strip()
        for keyword in (interest_bundle.get("keywords") or [])
        if str(keyword).strip()
    ]
    # 요청 주제와 콘텐츠 태그를 분리해 싣는다(2026-08-05 이송우 협의).
    #
    #   generation_topic  왜 이 리포트가 만들어졌는지 (요청 원본)
    #   tags              관심사 연결용. Service가 card_interest_tags로 소비 중이라
    #                     의미를 바꾸지 않는다 — 바꾸면 계약이 깨진다.
    #   content_tags      실제 작성된 내용에서 뽑은 검색·추천용 태그(REPORT-010)
    #
    # 요청 주제와 실제 내용은 갈릴 수 있다(실측: '의존성 구조' 요청이 강한 결합·
    # DDD·Application Layer를 다뤘다). 검색·추천에는 뒤쪽이 쓸모 있다.
    #
    # taxonomy_topic_ids는 위 두 태그와 층위가 다르다. tags·content_tags가 사람이
    # 읽는 자유 문자열이라면 이쪽은 Service·Agent가 공유하는 **식별자**다. Service는
    # 이것으로 뷰어 관심사와 카드의 교집합을 계산해 추천 피드를 만든다.
    taxonomy_version, taxonomy_topic_ids = await _derive_taxonomy_topics(
        connection,
        candidate_id=str(candidate["id"]),
        fallback_topics=_requested_topic_names(generation_request, topic),
    )
    publish_payload = {
        "title": generated.title,
        "summary": generated.summary,
        "body": generated.body,
        "citations": citation_payloads,
        "cover_image": cover_image_payload,
        "generation_topic": topic,
        "tags": [topic] if topic else [],
        "content_tags": list(generated.content_tags),
        "report_type": report_type,
        "request_idempotency_key": request_idempotency_key,
        "generation_scope": generation_scope,
        "source_interest_id": source_interest_id,
        "interest_profile_id": interest_profile_id,
        "bundle_keywords": bundle_keywords,
        "taxonomy_topic_ids": taxonomy_topic_ids,
        "taxonomy_version": taxonomy_version,
        "change_history_enabled": change_history_enabled,
    }
    await connection.execute(
        """
        INSERT INTO agent.publish_snapshots (
            candidate_id,
            user_id,
            content_id,
            version,
            snapshot_hash,
            payload,
            status,
            created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, 'ready', %s)
        """,
        (
            candidate["id"],
            user_id,
            content_id,
            content_version,
            snapshot_hash,
            Jsonb(publish_payload),
            candidate["created_at"],
        ),
    )
    await connection.execute(
        """
        INSERT INTO agent.event_outbox (
            aggregate_type,
            aggregate_id,
            event_type,
            deduplication_key,
            payload
        ) VALUES ('generated_content', %s, 'CONTENT_READY', %s, %s)
        ON CONFLICT (deduplication_key) DO NOTHING
        """,
        (
            content_id,
            f"content-ready:{content_id}:v{content_version}",
            Jsonb(
                {
                    "content_id": content_id,
                    "version": content_version,
                    "user_id": user_id,
                    "snapshot_hash": snapshot_hash,
                }
            ),
        ),
    )
    return {
        "generation_request_id": str(generation_request["id"]),
        "generation_run_id": str(generation_run["id"]),
        "content_candidate_id": str(candidate["id"]),
        "content_id": content_id,
        "version": content_version,
        "title": generated.title,
        "summary": generated.summary,
        "body": generated.body,
        "snapshot_hash": snapshot_hash,
        "citations": citation_payloads,
        "cover_image": cover_image_payload,
    }


async def load_global_document_freshness(
    connection: AsyncConnection[DictRow],
    document_version_ids: Sequence[str],
) -> dict[str, datetime]:
    """Global 풀 문서의 발행 시각을 검색 Context 식별자로 일괄 조회한다.

    풀 문서는 수집 캐시(`global_source_documents`)에 살고, 검색 Context에는
    `gsrc:<캐시 문서 UUID>` 식별자로 나타난다. Report Builder가 "풀 자료가
    실시간 수집을 대체할 만큼 신선한가"를 판정할 때 쓴다.

    발행일이 없는 문서는 결과에서 빠진다 — 호출자는 "모르는 것"과 "오래된
    것"을 구분해 처리해야 한다(모른다는 이유로 버리면 쓸 수 있는 근거가
    사라진다). `gsrc:` 형태가 아닌 식별자(개인 Wiki·테스트 더미)는 그대로
    무시한다.

    Args:
        connection: DB 연결
        document_version_ids: 검색 Context의 문서 식별자 목록

    Returns:
        {전달받은 식별자 그대로: 발행 시각(UTC)}
    """
    cache_ids: dict[str, str] = {}
    for value in document_version_ids:
        identifier = str(value or "").strip()
        cache_id = _global_cache_id_or_none(identifier)
        if cache_id is not None:
            cache_ids[cache_id] = identifier
    if not cache_ids:
        return {}
    cursor = await connection.execute(
        """
        SELECT id, published_at
        FROM agent.global_source_documents
        WHERE id = ANY(%s)
          AND published_at IS NOT NULL
        """,
        (list(cache_ids),),
    )
    freshness: dict[str, datetime] = {}
    for row in await cursor.fetchall():
        published = row["published_at"]
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        freshness[cache_ids[str(row["id"])]] = published
    return freshness
