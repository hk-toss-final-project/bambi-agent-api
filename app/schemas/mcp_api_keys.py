"""Service API용 MCP Personal Access Token 요청·응답 스키마."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class McpApiKeyCreateRequest(BaseModel):
    """새 MCP API Key의 표시 이름과 선택 만료 시각."""

    name: str = Field(min_length=1, max_length=64, description="사용자가 구분할 Key 이름")
    expires_at: datetime | None = Field(default=None, description="선택 만료 시각")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """공백뿐인 Key 이름을 거부하고 앞뒤 공백을 제거한다."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Key 이름은 공백일 수 없습니다.")
        return normalized

    @field_validator("expires_at")
    @classmethod
    def validate_expiration(cls, value: datetime | None) -> datetime | None:
        """만료 시각이 현재보다 미래인지 검증한다."""
        if value is None:
            return None
        aware_value = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        if aware_value <= datetime.now(UTC):
            raise ValueError("만료 시각은 현재보다 미래여야 합니다.")
        return aware_value


class McpApiKeyResponse(BaseModel):
    """원문과 Hash를 제외한 MCP API Key 관리 정보."""

    id: UUID
    name: str
    key_prefix: str
    scopes: list[str]
    status: str
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime
    revoked_at: datetime | None = None


class McpApiKeyCreateResponse(McpApiKeyResponse):
    """발급 직후 한 번만 원문 Key를 포함하는 응답."""

    api_key: str = Field(description="다시 조회할 수 없는 원문 API Key")
    token_type: str = Field(default="Bearer")


class McpApiKeyListResponse(BaseModel):
    """사용자 소유 MCP API Key 목록."""

    items: list[McpApiKeyResponse] = Field(default_factory=list)
