"""사용자별 개인 LLM Wiki 파생 데이터 초기화 기능.

사용자 원본과 원본 Version은 보존하고 Wiki 문서·관계·검색 Chunk·Build Snapshot·
관심사 Profile만 비활성화한다. 같은 사용자 Namespace 잠금으로 Wiki Build 저장과
직렬화하며 대기·실행 중인 Build Job도 함께 취소한다.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from infrastructure.persistence.features.personal_wiki import set_personal_wiki_scope

type DictRow = dict[str, Any]


async def reset_personal_wiki(
    connection: AsyncConnection[DictRow],
    *,
    user_id: str,
    request_id: str,
) -> dict[str, object]:
    """사용자 원본을 보존하고 개인 LLM Wiki 파생 상태를 멱등 초기화한다.

    Args:
        connection: 개인 Wiki PostgreSQL 연결
        user_id: 초기화할 사용자 식별자
        request_id: 초기화 요청 추적 식별자

    Returns:
        종류별 초기화 건수와 초기화 시각
    """
    namespace_key = f"user/{user_id}"
    async with connection.transaction():
        await set_personal_wiki_scope(connection, user_id=user_id)
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (namespace_key,),
        )
        reset_at_cursor = await connection.execute(
            "SELECT clock_timestamp() AS reset_at"
        )
        reset_at_row = await reset_at_cursor.fetchone()
        if reset_at_row is None:
            raise RuntimeError("개인 Wiki 초기화 시각을 조회하지 못했습니다.")
        reset_at = reset_at_row["reset_at"]

        cancelled_jobs = await _execute_count(
            connection,
            """
            UPDATE agent.agent_jobs
            SET status = 'cancelled',
                completed_at = COALESCE(completed_at, %s),
                locked_at = NULL,
                locked_by = NULL,
                lease_expires_at = NULL,
                retryable = false,
                error_code = 'WIKI_RESET',
                error_message = '사용자 요청으로 개인 LLM Wiki가 초기화되었습니다.',
                updated_at = %s
            WHERE user_id = %s
              AND job_type = 'personal_wiki_build'
              AND status IN ('queued', 'running')
            RETURNING id
            """,
            (reset_at, reset_at, user_id),
        )
        await connection.execute(
            """
            UPDATE agent.agent_job_attempts AS attempt
            SET status = 'failed',
                error_code = 'WIKI_RESET',
                error_message = '사용자 요청으로 개인 LLM Wiki가 초기화되었습니다.',
                completed_at = COALESCE(completed_at, %s)
            WHERE attempt.status = 'running'
              AND attempt.job_id IN (
                  SELECT id
                  FROM agent.agent_jobs
                  WHERE user_id = %s
                    AND job_type = 'personal_wiki_build'
                    AND status = 'cancelled'
                    AND error_code = 'WIKI_RESET'
              )
            """,
            (reset_at, user_id),
        )
        await _execute_count(
            connection,
            """
            UPDATE agent.wiki_relation_supports
            SET status = 'superseded',
                superseded_at = COALESCE(superseded_at, %s),
                updated_at = %s
            WHERE namespace_key = %s AND status = 'active'
            RETURNING id
            """,
            (reset_at, reset_at, namespace_key),
        )
        reset_relations = await _execute_count(
            connection,
            """
            UPDATE agent.wiki_document_relations
            SET status = 'superseded',
                superseded_at = COALESCE(superseded_at, %s),
                updated_at = %s
            WHERE namespace_key = %s AND status = 'active'
            RETURNING id
            """,
            (reset_at, reset_at, namespace_key),
        )
        unsearchable_chunks = await _execute_count(
            connection,
            """
            UPDATE agent.wiki_chunks
            SET is_searchable = false
            WHERE namespace_key = %s AND is_searchable
            RETURNING id
            """,
            (namespace_key,),
        )
        reset_documents = await _execute_count(
            connection,
            """
            UPDATE agent.wiki_documents
            SET status = 'deleted',
                deleted_at = COALESCE(deleted_at, %s),
                updated_at = %s
            WHERE namespace_key = %s AND deleted_at IS NULL
            RETURNING id
            """,
            (reset_at, reset_at, namespace_key),
        )
        retired_versions = await _execute_count(
            connection,
            """
            UPDATE agent.wiki_versions
            SET status = 'retired'
            WHERE user_id = %s
              AND namespace_key = %s
              AND status IN ('building', 'active')
            RETURNING id
            """,
            (user_id, namespace_key),
        )
        retired_profiles = await _execute_count(
            connection,
            """
            UPDATE agent.user_interest_profiles
            SET status = 'retired'
            WHERE user_id = %s AND status IN ('building', 'active')
            RETURNING id
            """,
            (user_id,),
        )
        await connection.execute(
            """
            INSERT INTO agent.wiki_source_events (
                user_id,
                source_event_id,
                source_type,
                occurred_at,
                payload,
                status,
                processed_at
            ) VALUES (%s, %s, 'reset', %s, %s, 'completed', %s)
            ON CONFLICT (user_id, source_event_id) DO NOTHING
            """,
            (
                user_id,
                f"wiki-reset:{request_id}",
                reset_at,
                Jsonb(
                    {
                        "reset_document_count": reset_documents,
                        "reset_relation_count": reset_relations,
                        "unsearchable_chunk_count": unsearchable_chunks,
                        "retired_wiki_version_count": retired_versions,
                        "retired_interest_profile_count": retired_profiles,
                        "cancelled_job_count": cancelled_jobs,
                    }
                ),
                reset_at,
            ),
        )
    return {
        "reset_document_count": reset_documents,
        "reset_relation_count": reset_relations,
        "unsearchable_chunk_count": unsearchable_chunks,
        "retired_wiki_version_count": retired_versions,
        "retired_interest_profile_count": retired_profiles,
        "cancelled_job_count": cancelled_jobs,
        "reset_at": reset_at,
    }


async def _execute_count(
    connection: AsyncConnection[DictRow],
    query: str,
    params: tuple[object, ...],
) -> int:
    """`RETURNING` 갱신 Query를 실행하고 반영 Row 수를 반환한다."""
    cursor = await connection.execute(query, params)
    return len(await cursor.fetchall())
