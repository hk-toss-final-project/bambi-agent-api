"""실제 PostgreSQL 스키마에서 Wiki Navigator 관계 순회를 검증한다."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import pytest
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from domain.personal_wiki.navigation.features.traversal import wnav_003


def _test_database_url() -> str:
    """통합 테스트 전용 PostgreSQL URL을 반환하거나 테스트를 건너뛴다."""
    database_url = os.getenv("AGENT_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip(
            "AGENT_TEST_DATABASE_URL이 없어 PostgreSQL 통합 테스트를 건너뜁니다."
        )
    return database_url


async def _insert_navigation_fixture(
    connection: AsyncConnection[dict[str, object]],
    *,
    user_id: str,
) -> tuple[UUID, UUID]:
    """한 관계를 두 원본 support가 지지하는 개인 Wiki Fixture를 저장한다."""
    namespace_key = f"user/{user_id}"
    source_document_id = uuid4()
    target_document_id = uuid4()
    source_record_id = uuid4()
    source_version_id = uuid4()
    relation_id = uuid4()
    job_ids = (uuid4(), uuid4())

    for index, job_id in enumerate(job_ids, start=1):
        await connection.execute(
            """
            INSERT INTO agent.agent_jobs (
                id, feature_id, job_type, user_id, idempotency_key
            ) VALUES (%s, 'WNAV-003', 'wiki_navigation_test', %s, %s)
            """,
            (job_id, user_id, f"navigation-integration-{index}-{job_id}"),
        )

    for document_id, key, title_marker in (
        (source_document_id, "seed", "a"),
        (target_document_id, "neighbor", "b"),
    ):
        await connection.execute(
            """
            INSERT INTO agent.wiki_documents (
                id,
                knowledge_scope,
                namespace_key,
                user_id,
                source_type,
                content_hash,
                document_kind,
                document_key,
                file_path
            ) VALUES (%s, 'personal', %s, %s, 'memo', %s, 'concept', %s, %s)
            """,
            (
                document_id,
                namespace_key,
                user_id,
                title_marker * 64,
                f"{key}-{document_id}",
                f"concepts/{key}-{document_id}.md",
            ),
        )

    await connection.execute(
        """
        INSERT INTO agent.user_source_documents (
            id, user_id, namespace_key, source_type, content_hash
        ) VALUES (%s, %s, %s, 'memo', %s)
        """,
        (source_record_id, user_id, namespace_key, "c" * 64),
    )
    await connection.execute(
        """
        INSERT INTO agent.user_source_document_versions (
            id,
            source_document_id,
            namespace_key,
            version,
            title,
            raw_content,
            content_hash
        ) VALUES (%s, %s, %s, 1, 'Navigator 통합 근거', '관계 근거 본문', %s)
        """,
        (source_version_id, source_record_id, namespace_key, "d" * 64),
    )
    await connection.execute(
        """
        INSERT INTO agent.wiki_document_relations (
            id,
            source_document_id,
            target_document_id,
            namespace_key,
            relation_type,
            provenance_kind,
            confidence,
            review_status,
            metadata
        ) VALUES (
            %s, %s, %s, %s, 'associated_with',
            'source_explicit', 0.95, 'accepted',
            '{"rationale": "두 문서가 명시적으로 연결됨"}'::jsonb
        )
        """,
        (relation_id, source_document_id, target_document_id, namespace_key),
    )

    for index, (job_id, confidence) in enumerate(
        zip(job_ids, (0.93, 0.87), strict=True),
        start=1,
    ):
        await connection.execute(
            """
            INSERT INTO agent.wiki_relation_supports (
                relation_id,
                namespace_key,
                source_document_version_id,
                build_job_id,
                provenance_kind,
                confidence,
                review_status,
                evidence,
                metadata
            ) VALUES (
                %s, %s, %s, %s, 'source_explicit', %s, 'accepted', %s,
                '{"rationale": "통합 테스트 support"}'::jsonb
            )
            """,
            (
                relation_id,
                namespace_key,
                source_version_id,
                job_id,
                confidence,
                f"근거-{index}",
            ),
        )

    return source_document_id, target_document_id


async def _run_navigation_integration() -> None:
    """Fixture를 만든 뒤 실제 WNAV-003 1-hop 순회 결과를 검증한다."""
    connection = await AsyncConnection.connect(
        _test_database_url(),
        row_factory=dict_row,
    )
    try:
        async with connection.transaction(force_rollback=True):
            user_id = f"navigator-integration-{uuid4().hex}"
            source_document_id, target_document_id = await _insert_navigation_fixture(
                connection,
                user_id=user_id,
            )

            traversal = await wnav_003(
                connection,
                user_id=user_id,
                seed_document_ids=[str(source_document_id)],
                max_depth=1,
                max_pages=6,
            )

            assert traversal.document_ids == (
                str(source_document_id),
                str(target_document_id),
            )
            assert len(traversal.relations) == 1
            relation = traversal.relations[0]
            assert relation.hops == 1
            assert relation.traversal_direction == "outgoing"
            assert [support.confidence for support in relation.supports] == [
                0.93,
                0.87,
            ]
            assert [support.evidence for support in relation.supports] == [
                "근거-1",
                "근거-2",
            ]
    finally:
        await connection.close()


def test_wiki_navigation_expands_one_hop_with_multiple_supports() -> None:
    """실제 PostgreSQL에서 복합 PK 관계와 여러 support 집계를 검증한다."""
    asyncio.run(_run_navigation_integration())
