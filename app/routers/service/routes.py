"""Service API가 호출하는 FastAPI MVP 내부 라우터."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, status

from app.dependencies import get_mvp_service
from app.schemas.mvp import (
    AcceptedJobResponse,
    ContentMarkRequest,
    GenerationRequest,
    JobResultResponse,
    JobStatusResponse,
    UrlWikiSourceRequest,
    UserContextResponse,
    UserContextUpsertRequest,
    WebClippingRequest,
)
from app.services.mvp import AgentApiMvpService

router = APIRouter(tags=["service-api"])
UserId = Annotated[str, Path(min_length=1, max_length=128, description="사용자 ID")]


def _request_id(request: Request) -> str:
    """추적 미들웨어가 생성한 Request ID를 반환한다."""
    return request.state.request_id


@router.put(
    "/users/{user_id}/context",
    response_model=UserContextResponse,
    operation_id="svc_001",
)
async def upsert_user_context(
    user_id: UserId,
    payload: UserContextUpsertRequest,
    request: Request,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> UserContextResponse:
    """[SVC-001] Service의 최신 사용자 설정을 Agent 컨텍스트에 반영한다."""
    return await service.upsert_user_context(user_id, payload, _request_id(request))


@router.post(
    "/users/{user_id}/wiki-sources/clippings",
    response_model=AcceptedJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="svc_002",
)
async def request_web_clipping(
    user_id: UserId,
    payload: WebClippingRequest,
    request: Request,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> AcceptedJobResponse:
    """[SVC-002] 웹 클리핑을 Personal Wiki Builder Job으로 등록한다."""
    return await service.enqueue_job(
        feature_id="SVC-002",
        job_type="personal_wiki_web_clipping",
        user_id=user_id,
        idempotency_key=payload.source_event_id,
        request_id=_request_id(request),
        payload=payload.model_dump(mode="json"),
    )


@router.post(
    "/users/{user_id}/wiki-sources/urls",
    response_model=AcceptedJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="svc_003",
)
async def request_url_wiki_source(
    user_id: UserId,
    payload: UrlWikiSourceRequest,
    request: Request,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> AcceptedJobResponse:
    """[SVC-003] 사용자 입력 URL을 Personal Wiki Builder Job으로 등록한다."""
    return await service.enqueue_job(
        feature_id="SVC-003",
        job_type="personal_wiki_url",
        user_id=user_id,
        idempotency_key=payload.source_event_id,
        request_id=_request_id(request),
        payload=payload.model_dump(mode="json"),
    )


@router.post(
    "/users/{user_id}/wiki-sources/content-marks",
    response_model=AcceptedJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="svc_004",
)
async def request_content_mark(
    user_id: UserId,
    payload: ContentMarkRequest,
    request: Request,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> AcceptedJobResponse:
    """[SVC-004] 위키마킹한 생성 콘텐츠를 Personal Wiki Builder Job으로 등록한다."""
    return await service.enqueue_job(
        feature_id="SVC-004",
        job_type="personal_wiki_content_mark",
        user_id=user_id,
        idempotency_key=payload.source_event_id,
        request_id=_request_id(request),
        payload=payload.model_dump(mode="json"),
    )


@router.post(
    "/users/{user_id}/generations",
    response_model=AcceptedJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="svc_008",
)
async def request_generation(
    user_id: UserId,
    payload: GenerationRequest,
    request: Request,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> AcceptedJobResponse:
    """[SVC-008] 밤비 개인화 콘텐츠 생성 Job을 등록한다."""
    return await service.enqueue_job(
        feature_id="SVC-008",
        job_type="bambi_generation",
        user_id=user_id,
        idempotency_key=payload.idempotency_key,
        request_id=_request_id(request),
        payload=payload.model_dump(mode="json"),
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    operation_id="svc_013",
)
async def get_job_status(
    job_id: Annotated[str, Path(min_length=1, max_length=128)],
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> JobStatusResponse:
    """[SVC-013] Agent Job의 현재 상태와 진행률을 조회한다."""
    return await service.get_job(job_id)


@router.get(
    "/jobs/{job_id}/result",
    response_model=JobResultResponse,
    operation_id="svc_014",
)
async def get_job_result(
    job_id: Annotated[str, Path(min_length=1, max_length=128)],
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> JobResultResponse:
    """[SVC-014] 완료된 Agent Job의 기능별 결과를 조회한다."""
    return await service.get_job_result(job_id)
