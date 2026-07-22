"""개인 Wiki 증분 Build 오케스트레이션.

원본·기존 Wiki 조회, LLM 분류, Build 계획, DB 영속화를 WBA-001 한 건의
실행 경계로 묶는다. LLM 호출 동안은 DB Transaction을 열어 두지 않는다.
"""

from asyncio import to_thread
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection

from agent.wiki_builder.features.classification import classify_source_for_wiki
from agent.wiki_builder.features.planning import build_wiki_plan
from agent.wiki_builder.models import WikiBuildPlan, WikiClassification
from infrastructure.persistence.api import (
    PersistedWikiBuild,
    get_user_source_document_version_for_agent,
    list_existing_wiki_entries,
    list_existing_wiki_relations,
    persist_wiki_build,
    set_personal_wiki_scope,
)

from shared.contracts import FeatureRequest, FeatureResult

type DictRow = dict[str, Any]
type WikiClassifier = Callable[..., WikiClassification]
type WikiBuildRunner = Callable[..., Awaitable[dict[str, object]]]


async def build_incremental_wiki(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_document_version_id: str,
    job_id: str,
    model: str = "gpt-4.1-mini",
    classifier: WikiClassifier = classify_source_for_wiki,
    generated_at: str | None = None,
) -> tuple[PersistedWikiBuild, WikiBuildPlan]:
    """저장된 클리핑 Version 하나를 증분 개인 Wiki Build로 처리한다.

    조회 Transaction을 닫은 뒤 LLM을 호출하고, 결과를 별도 Transaction에서
    문서·Version·출처·관계·Chunk·Snapshot으로 저장한다.
    """
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        source = await get_user_source_document_version_for_agent(
            connection,
            user_id=user_id,
            source_document_version_id=source_document_version_id,
        )
        if source is None:
            raise ValueError(
                f"개인 Wiki 원본 Version을 찾을 수 없습니다: {source_document_version_id}"
            )
        if not source.raw_content:
            raise ValueError(
                f"DB에 Markdown 원문이 없습니다: {source_document_version_id}"
            )
        existing_entities = await list_existing_wiki_entries(
            connection, user_id=user_id, document_kind="entity"
        )
        existing_concepts = await list_existing_wiki_entries(
            connection, user_id=user_id, document_kind="concept"
        )
        existing_relations = await list_existing_wiki_relations(
            connection,
            namespace_key=source.namespace_key,
        )

    classification = await to_thread(
        classifier,
        source_title=source.title,
        source_content=source.raw_content,
        source_description=source.description,
        source_tags=source.tags,
        existing_entities=existing_entities,
        existing_concepts=existing_concepts,
        model=model,
    )
    timestamp = generated_at or datetime.now(UTC).isoformat()
    plan = build_wiki_plan(
        source_title=source.title,
        source_url=source.canonical_url,
        source_tags=source.tags,
        source_content_hash=source.content_hash,
        source_size_bytes=len(source.raw_content.encode("utf-8")),
        classification=classification,
        existing_entities=existing_entities,
        existing_concepts=existing_concepts,
        generated_at=timestamp,
        model=model,
        existing_relations=existing_relations,
    )
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        persisted = await persist_wiki_build(
            connection,
            source=source,
            plan=plan,
            job_id=job_id,
        )
    return persisted, plan


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def wba_001(
    runner: WikiBuildRunner,
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    source_document_version_id: str,
    job_id: str,
    model: str = "gpt-4.1-mini",
) -> dict[str, object]:
    """[WBA-001] Incremental Wiki Build.

    새로 추가된 사용자 데이터만 개인 Wiki에 반영한다.
    """
    if not user_id:
        raise ValueError("WBA-001에 user_id가 필요합니다.")
    if not source_document_version_id:
        raise ValueError("WBA-001에 source_document_version_id가 필요합니다.")
    if not job_id:
        raise ValueError("WBA-001에 job_id가 필요합니다.")
    if not model:
        raise ValueError("WBA-001의 model은 빈 문자열이면 안 됩니다.")
    return await runner(
        connection,
        user_id=user_id,
        source_document_version_id=source_document_version_id,
        job_id=job_id,
        model=model,
    )


async def wba_002(request: FeatureRequest) -> FeatureResult:
    """[WBA-002] Full Wiki Rebuild.

    전체 개인 Wiki를 재분류하고 재구성한다.
    """
    raise NotImplementedError("[WBA-002] 기능 구현이 필요합니다.")
