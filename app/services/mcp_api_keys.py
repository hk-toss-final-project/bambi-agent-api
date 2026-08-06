"""Service API가 사용하는 MCP Personal Access Token 애플리케이션 서비스."""

from collections.abc import Mapping

from app.exceptions import AgentApiError, ErrorDetail
from app.schemas.mcp_api_keys import (
    McpApiKeyCreateRequest,
    McpApiKeyCreateResponse,
    McpApiKeyListResponse,
    McpApiKeyResponse,
)
from app.security.api_keys.api import ApiKeyLifecycleRepository, key_001, key_002, key_005


class McpApiKeyService:
    """인증 사용자 범위로 API Key 발급·조회·폐기를 조정한다."""

    def __init__(self, repository: ApiKeyLifecycleRepository) -> None:
        """API Key 수명 주기 저장소를 주입한다."""
        self._repository = repository

    @staticmethod
    def _response(record: Mapping[str, object]) -> McpApiKeyResponse:
        """저장소 Row를 원문·Hash 없는 관리 응답으로 변환한다."""
        return McpApiKeyResponse.model_validate(dict(record))

    async def create(
        self,
        user_id: str,
        payload: McpApiKeyCreateRequest,
        *,
        request_id: str,
    ) -> McpApiKeyCreateResponse:
        """사용자 Wiki 읽기 전용 MCP API Key를 발급한다."""
        issued = await key_001(
            self._repository,
            principal_id=user_id,
            name=payload.name,
            expires_at=payload.expires_at,
            request_id=request_id,
        )
        response = self._response(issued.record)
        return McpApiKeyCreateResponse(
            **response.model_dump(),
            api_key=issued.raw_key,
        )

    async def list(self, user_id: str) -> McpApiKeyListResponse:
        """사용자가 발급한 MCP API Key 목록을 반환한다."""
        records = await key_002(self._repository, principal_id=user_id)
        return McpApiKeyListResponse(items=[self._response(record) for record in records])

    async def revoke(
        self, user_id: str, key_id: str, *, request_id: str
    ) -> McpApiKeyResponse:
        """사용자 소유 MCP API Key를 영구 폐기한다."""
        record = await key_005(
            self._repository,
            principal_id=user_id,
            key_id=key_id,
            request_id=request_id,
        )
        if record is None:
            raise AgentApiError(
                404,
                ErrorDetail(
                    code="MCP_API_KEY_NOT_FOUND",
                    message="MCP API Key를 찾을 수 없습니다.",
                ),
            )
        return self._response(record)
