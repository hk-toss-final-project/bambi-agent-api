"""MCP API Key 발급·검증·폐기 도메인 기능을 검증한다."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.security.api_keys.api import key_001, key_005, key_014


class _FakeApiKeyRepository:
    """원문을 저장하지 않는 인메모리 API Key 저장소 대역."""

    def __init__(self) -> None:
        """테스트용 저장 상태를 초기화한다."""
        self.records: dict[str, dict[str, object]] = {}
        self.used: list[str] = []

    async def create_api_key(self, **values: object) -> dict[str, object]:
        """Hash와 Prefix만 포함한 발급 레코드를 저장한다."""
        record = {
            # psycopg의 uuid 컬럼 반환 타입과 동일하게 유지한다.
            "id": UUID("11111111-1111-1111-1111-111111111111"),
            "status": "active",
            "last_used_at": None,
            "created_at": datetime(2026, 8, 6, tzinfo=UTC),
            "revoked_at": None,
            **values,
        }
        self.records[str(record["key_prefix"])] = record
        return record

    async def list_api_keys(self, principal_id: str) -> list[dict[str, object]]:
        """사용자 소유 Key만 반환한다."""
        return [
            record
            for record in self.records.values()
            if record["principal_id"] == principal_id
        ]

    async def revoke_api_key(
        self, *, principal_id: str, key_id: str, request_id: str
    ) -> dict[str, object] | None:
        """소유자가 일치하는 Key를 폐기한다."""
        for record in self.records.values():
            if str(record["id"]) == key_id and record["principal_id"] == principal_id:
                record["status"] = "revoked"
                record["revoked_at"] = datetime(2026, 8, 6, tzinfo=UTC)
                return record
        return None

    async def find_api_key_by_prefix(
        self, key_prefix: str
    ) -> dict[str, object] | None:
        """Prefix가 일치하는 검증 후보를 반환한다."""
        return self.records.get(key_prefix)

    async def mark_api_key_used(self, key_id: str) -> None:
        """검증 성공 Key ID를 기록한다."""
        self.used.append(key_id)


def test_key_issue_stores_only_hash_and_authenticates_owner() -> None:
    """발급 원문은 저장하지 않고 Bearer 검증에서 사용자 주체를 복원한다."""
    asyncio.run(_assert_key_issue_stores_only_hash_and_authenticates_owner())


async def _assert_key_issue_stores_only_hash_and_authenticates_owner() -> None:
    """비동기 발급·인증 시나리오의 세부 동작을 검증한다."""
    repository = _FakeApiKeyRepository()
    now = datetime(2026, 8, 6, tzinfo=UTC)

    issued = await key_001(
        repository,
        principal_id="42",
        name="Claude",
        expires_at=now + timedelta(days=90),
        request_id="request-1",
    )
    stored = next(iter(repository.records.values()))
    principal = await key_014(repository, raw_key=issued.raw_key, now=now)

    assert issued.raw_key.startswith("bmb_mcp_")
    assert "raw_key" not in stored
    assert stored["key_hash"] != issued.raw_key
    assert stored["scopes"] == ("wiki:read",)
    assert principal is not None
    assert principal.user_id == "42"
    assert repository.used == [principal.key_id]


def test_key_authentication_rejects_modified_expired_and_revoked_keys() -> None:
    """변조·만료·폐기된 Key가 Personal Wiki 주체를 만들지 못한다."""
    asyncio.run(_assert_key_authentication_rejects_invalid_keys())


async def _assert_key_authentication_rejects_invalid_keys() -> None:
    """비동기 변조·만료·폐기 검증 시나리오를 실행한다."""
    repository = _FakeApiKeyRepository()
    now = datetime(2026, 8, 6, tzinfo=UTC)
    issued = await key_001(
        repository,
        principal_id="42",
        name="GPT",
        expires_at=now + timedelta(days=1),
        request_id="request-2",
    )

    assert await key_014(repository, raw_key=f"{issued.raw_key}x", now=now) is None
    assert (
        await key_014(repository, raw_key=issued.raw_key, now=now + timedelta(days=2))
        is None
    )
    await key_005(
        repository,
        principal_id="42",
        key_id=str(issued.record["id"]),
        request_id="request-3",
    )
    assert await key_014(repository, raw_key=issued.raw_key, now=now) is None


def test_key_issue_can_grant_write_scope_and_rejects_unknown_scope() -> None:
    """wiki:write 요청 시 wiki:read를 함께 부여하고, 허용 밖 Scope는 거부한다."""
    asyncio.run(_assert_key_issue_scope_handling())


async def _assert_key_issue_scope_handling() -> None:
    """비동기 Scope 정규화·검증 시나리오를 실행한다."""
    repository = _FakeApiKeyRepository()
    now = datetime(2026, 8, 6, tzinfo=UTC)

    write_issued = await key_001(
        repository,
        principal_id="42",
        name="Claude Write",
        expires_at=now + timedelta(days=90),
        request_id="request-4",
        scopes=("wiki:write",),
    )
    write_record = repository.records[write_issued.record["key_prefix"]]
    assert write_record["scopes"] == ("wiki:read", "wiki:write")

    try:
        await key_001(
            repository,
            principal_id="42",
            name="Bad Scope",
            expires_at=now + timedelta(days=90),
            request_id="request-5",
            scopes=("wiki:delete",),
        )
        raised = False
    except ValueError:
        raised = True
    assert raised
