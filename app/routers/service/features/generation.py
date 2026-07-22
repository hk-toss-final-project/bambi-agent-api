"""Service 개인화 콘텐츠 생성 접수 기능 구현."""

from typing import Protocol

from app.schemas.mvp import AcceptedJobResponse, GenerationRequest


class GenerationSubmissionService(Protocol):
    """개인화 콘텐츠 생성 접수에 필요한 애플리케이션 서비스 경계."""

    async def submit_generation(
        self, *, user_id: str, payload: GenerationRequest, request_id: str
    ) -> AcceptedJobResponse:
        """개인화 콘텐츠 생성 작업을 접수한다."""
        ...


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_008(
    service: GenerationSubmissionService,
    *,
    user_id: str,
    payload: GenerationRequest,
    request_id: str,
) -> AcceptedJobResponse:
    """[SVC-008] 콘텐츠 생성 요청.

    리포트 생성기의 콘텐츠 생성을 요청한다.
    """
    return await service.submit_generation(
        user_id=user_id, payload=payload, request_id=request_id
    )
