"""PostgreSQL 기반 MCP Personal Access Token 저장소."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


type DictRow = dict[str, Any]


class PostgresApiKeyRepository:
    """API Key Hash·수명 주기·감사 로그를 PostgreSQL에 저장한다."""

    def __init__(self, database_url: str) -> None:
        """지연 시작 방식의 API Key PostgreSQL Pool을 구성한다."""
        self._pool: AsyncConnectionPool[DictRow] = AsyncConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=4,
            open=False,
            kwargs={"row_factory": dict_row},
        )

    async def startup(self) -> None:
        """API Key 저장용 연결 Pool을 연다."""
        await self._pool.open(wait=True)

    async def shutdown(self) -> None:
        """API Key 저장용 연결 Pool을 종료한다."""
        await self._pool.close()

    async def create_api_key(
        self,
        *,
        principal_id: str,
        name: str,
        key_prefix: str,
        key_hash: str,
        scopes: Sequence[str],
        expires_at: datetime | None,
        request_id: str,
    ) -> Mapping[str, object]:
        """원문 없이 API Key 식별 정보와 발급 감사 로그를 저장한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute(
                    """
                    INSERT INTO agent.api_keys (
                        key_prefix, key_hash, principal_id, name, scopes, expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, key_prefix, principal_id, name, scopes, status,
                              expires_at, last_used_at, created_at, revoked_at
                    """,
                    (key_prefix, key_hash, principal_id, name, list(scopes), expires_at),
                )
                record = await cursor.fetchone()
                assert record is not None
                await connection.execute(
                    """
                    INSERT INTO agent.audit_logs (
                        actor_type, actor_id, action, resource_type, resource_id,
                        target_user_id, request_id, succeeded, details
                    )
                    VALUES ('service-api', %s, 'api_key.created', 'api_key', %s,
                            %s, %s, true, %s)
                    """,
                    (
                        principal_id,
                        record["id"],
                        principal_id,
                        request_id,
                        Jsonb({"key_prefix": key_prefix, "scopes": list(scopes)}),
                    ),
                )
        return record

    async def list_api_keys(self, principal_id: str) -> Sequence[Mapping[str, object]]:
        """사용자 소유 API Key를 원문과 Hash 없이 최신순으로 반환한다."""
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE agent.api_keys
                SET status = 'expired'
                WHERE principal_id = %s
                  AND status = 'active'
                  AND expires_at <= clock_timestamp()
                """,
                (principal_id,),
            )
            cursor = await connection.execute(
                """
                SELECT id, key_prefix, principal_id, name, scopes, status,
                       expires_at, last_used_at, created_at, revoked_at
                FROM agent.api_keys
                WHERE principal_id = %s
                ORDER BY created_at DESC
                """,
                (principal_id,),
            )
            return await cursor.fetchall()

    async def revoke_api_key(
        self, *, principal_id: str, key_id: str, request_id: str
    ) -> Mapping[str, object] | None:
        """사용자 소유 API Key를 멱등하게 폐기하고 최초 폐기만 감사 기록한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute(
                    """
                    UPDATE agent.api_keys
                    SET status = 'revoked', revoked_at = clock_timestamp()
                    WHERE id = %s::uuid
                      AND principal_id = %s
                      AND status <> 'revoked'
                    RETURNING id, key_prefix, principal_id, name, scopes, status,
                              expires_at, last_used_at, created_at, revoked_at
                    """,
                    (key_id, principal_id),
                )
                record = await cursor.fetchone()
                if record is not None:
                    await connection.execute(
                        """
                        INSERT INTO agent.audit_logs (
                            actor_type, actor_id, action, resource_type, resource_id,
                            target_user_id, request_id, succeeded, details
                        )
                        VALUES ('service-api', %s, 'api_key.revoked', 'api_key', %s,
                                %s, %s, true, '{}'::jsonb)
                        """,
                        (principal_id, key_id, principal_id, request_id),
                    )
                    return record
                existing_cursor = await connection.execute(
                    """
                    SELECT id, key_prefix, principal_id, name, scopes, status,
                           expires_at, last_used_at, created_at, revoked_at
                    FROM agent.api_keys
                    WHERE id = %s::uuid AND principal_id = %s
                    """,
                    (key_id, principal_id),
                )
                return await existing_cursor.fetchone()

    async def find_api_key_by_prefix(
        self, key_prefix: str
    ) -> Mapping[str, object] | None:
        """인증 후보 Key의 Hash·주체·Scope를 Prefix로 조회한다."""
        async with self._pool.connection() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    UPDATE agent.api_keys
                    SET status = 'expired'
                    WHERE key_prefix = %s
                      AND status = 'active'
                      AND expires_at <= clock_timestamp()
                    """,
                    (key_prefix,),
                )
                cursor = await connection.execute(
                    """
                    SELECT id, key_prefix, key_hash, principal_id, scopes, status, expires_at
                    FROM agent.api_keys
                    WHERE key_prefix = %s
                    """,
                    (key_prefix,),
                )
                return await cursor.fetchone()

    async def mark_api_key_used(self, key_id: str) -> None:
        """검증 성공 Key의 마지막 사용 시각을 현재 시각으로 갱신한다."""
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                UPDATE agent.api_keys
                SET last_used_at = clock_timestamp()
                WHERE id = %s::uuid AND status = 'active'
                """,
                (key_id,),
            )
