"""API Key Scope와 Personal Wiki 사용자 권한 검증 기능."""

import hmac
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


from .security import key_008, parse_api_key_prefix


class ApiKeyAuthorizationRepository(Protocol):
    """API Key 인증 저장소가 제공해야 하는 최소 계약."""

    async def find_api_key_by_prefix(
        self, key_prefix: str
    ) -> Mapping[str, object] | None:
        """공개 Prefix로 검증 후보 Key를 조회한다."""
        ...

    async def mark_api_key_used(self, key_id: str) -> None:
        """검증에 성공한 Key의 마지막 사용 시각을 갱신한다."""
        ...


@dataclass(frozen=True, slots=True)
class ApiKeyPrincipal:
    """검증된 API Key에서 도출한 MCP 호출 주체."""

    key_id: str
    user_id: str
    scopes: tuple[str, ...]
    expires_at: datetime | None


async def key_009(scopes: Sequence[str], required_scope: str) -> bool:
    """[KEY-009] API Key Scope 설정.

    Key로 사용할 수 있는 기능 범위를 설정한다.
    """
    return required_scope in scopes


async def key_014(
    repository: ApiKeyAuthorizationRepository,
    *,
    raw_key: str,
    now: datetime,
) -> ApiKeyPrincipal | None:
    """[KEY-014] Personal Wiki 접근 권한.

    원문 Key를 검증하고 해당 Key에 연결된 사용자 Wiki 주체를 반환한다.
    """
    try:
        key_prefix = parse_api_key_prefix(raw_key)
    except ValueError:
        return None
    record = await repository.find_api_key_by_prefix(key_prefix)
    if record is None or record.get("status") != "active":
        return None
    expires_at = record.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at <= now:
        return None
    scopes = tuple(str(scope) for scope in record.get("scopes", ()))
    if not await key_009(scopes, "wiki:read"):
        return None
    generated = await key_008(raw_key)
    stored_hash = str(record.get("key_hash", ""))
    if not hmac.compare_digest(generated.key_hash, stored_hash):
        return None
    key_id = str(record["id"])
    await repository.mark_api_key_used(key_id)
    return ApiKeyPrincipal(
        key_id=key_id,
        user_id=str(record["principal_id"]),
        scopes=scopes,
        expires_at=expires_at if isinstance(expires_at, datetime) else None,
    )
