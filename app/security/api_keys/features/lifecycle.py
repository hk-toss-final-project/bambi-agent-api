"""MCP Personal Access Token 발급·조회·폐기 기능."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from shared.contracts import FeatureRequest, FeatureResult

from .security import GeneratedApiKey, key_008


type ApiKeyRecord = Mapping[str, object]

ALLOWED_API_KEY_SCOPES = frozenset({"wiki:read", "wiki:write"})


class ApiKeyLifecycleRepository(Protocol):
    """API Key 수명 주기 저장소가 제공해야 하는 최소 계약."""

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
    ) -> ApiKeyRecord:
        """Hash 형태의 새 API Key를 저장한다."""
        ...

    async def list_api_keys(self, principal_id: str) -> Sequence[ApiKeyRecord]:
        """사용자가 발급한 API Key를 최신순으로 조회한다."""
        ...

    async def revoke_api_key(
        self, *, principal_id: str, key_id: str, request_id: str
    ) -> ApiKeyRecord | None:
        """사용자 소유 API Key를 영구 폐기한다."""
        ...


@dataclass(frozen=True, slots=True)
class IssuedApiKey:
    """발급 직후 한 번만 원문을 포함하는 API Key 결과."""

    raw_key: str
    record: ApiKeyRecord


async def key_001(
    repository: ApiKeyLifecycleRepository,
    *,
    principal_id: str,
    name: str,
    expires_at: datetime | None,
    request_id: str,
    scopes: Sequence[str] | None = None,
) -> IssuedApiKey:
    """[KEY-001] API Key 발급.

    기본값은 Personal Wiki 읽기(`wiki:read`) Scope만 부여한다. 호출자가
    `wiki:write`를 명시적으로 요청하면 쓰기 Scope를 추가하되, 쓰기는 항상
    읽기를 동반하도록 `wiki:read`를 함께 부여한다.
    """
    normalized = tuple(dict.fromkeys(scopes)) if scopes else ("wiki:read",)
    unknown = [scope for scope in normalized if scope not in ALLOWED_API_KEY_SCOPES]
    if unknown:
        raise ValueError(f"허용하지 않는 API Key Scope입니다: {', '.join(unknown)}")
    if "wiki:write" in normalized and "wiki:read" not in normalized:
        normalized = ("wiki:read", *normalized)
    generated: GeneratedApiKey = await key_008()
    record = await repository.create_api_key(
        principal_id=principal_id,
        name=name,
        key_prefix=generated.key_prefix,
        key_hash=generated.key_hash,
        scopes=normalized,
        expires_at=expires_at,
        request_id=request_id,
    )
    return IssuedApiKey(raw_key=generated.raw_key, record=record)


async def key_002(
    repository: ApiKeyLifecycleRepository, *, principal_id: str
) -> Sequence[ApiKeyRecord]:
    """[KEY-002] API Key 조회.

    발급된 Key의 상태와 설정을 조회한다.
    """
    return await repository.list_api_keys(principal_id)


async def key_003(request: FeatureRequest) -> FeatureResult:
    """[KEY-003] API Key 이름 변경.

    관리 편의를 위해 Key 이름을 수정한다.
    """
    raise NotImplementedError("[KEY-003] 기능 구현이 필요합니다.")


async def key_004(request: FeatureRequest) -> FeatureResult:
    """[KEY-004] API Key 비활성화.

    Key 사용을 일시 중지한다.
    """
    raise NotImplementedError("[KEY-004] 기능 구현이 필요합니다.")


async def key_005(
    repository: ApiKeyLifecycleRepository,
    *,
    principal_id: str,
    key_id: str,
    request_id: str,
) -> ApiKeyRecord | None:
    """[KEY-005] API Key 폐기.

    Key를 영구적으로 사용 중지한다.
    """
    return await repository.revoke_api_key(
        principal_id=principal_id,
        key_id=key_id,
        request_id=request_id,
    )


async def key_006(request: FeatureRequest) -> FeatureResult:
    """[KEY-006] API Key Rotation.

    새 Key를 발급하고 이전 Key를 교체한다.
    """
    raise NotImplementedError("[KEY-006] 기능 구현이 필요합니다.")


async def key_007(request: FeatureRequest) -> FeatureResult:
    """[KEY-007] API Key 만료 설정.

    Key의 사용 가능 기간을 설정한다.
    """
    raise NotImplementedError("[KEY-007] 기능 구현이 필요합니다.")
