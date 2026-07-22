"""Service 사용자 컨텍스트 반영 기능 구현."""

from typing import Protocol

from app.schemas.mvp import UserContextResponse, UserContextUpsertRequest


class UserContextService(Protocol):
    """사용자 컨텍스트 반영에 필요한 애플리케이션 서비스 경계."""

    async def upsert_user_context(
        self,
        user_id: str,
        payload: UserContextUpsertRequest,
        request_id: str,
    ) -> UserContextResponse:
        """사용자 컨텍스트를 저장하고 반영 결과를 반환한다."""
        ...


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_001(
    service: UserContextService,
    user_id: str,
    payload: UserContextUpsertRequest,
    request_id: str,
) -> UserContextResponse:
    """[SVC-001] 사용자 컨텍스트 전달.

    서비스 사용자 설정을 Agent 컨텍스트로 전달한다.
    """
    return await service.upsert_user_context(user_id, payload, request_id)
