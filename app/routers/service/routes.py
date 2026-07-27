"""Service API가 호출하는 FastAPI MVP 내부 라우터."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, status

from app.dependencies import (
    get_mvp_service,
    get_interest_service,
    get_generated_content_service,
    get_wiki_document_service,
    get_wiki_graph_service,
)
from app.schemas.generated_content import (
    GeneratedContentDetailResponse,
    GeneratedContentListResponse,
)
from app.schemas.interests import InterestProfileResponse, InterestRebuildRequest
from app.schemas.mvp import (
    AcceptedJobResponse,
    ContentMarkRequest,
    FeedbackSignalsRequest,
    FeedbackSignalsResponse,
    GenerationRequest,
    JobResultResponse,
    JobStatusResponse,
    UrlWikiSourceRequest,
    UserContextResponse,
    UserContextUpsertRequest,
    WebClippingRequest,
)
from app.schemas.wiki import (
    WikiBuildDetailResponse,
    WikiDocumentDetailResponse,
    WikiDocumentListResponse,
    WikiGraphResponse,
    WikiTopNodesResponse,
)
from app.routers.service.api import (
    svc_001,
    svc_002,
    svc_003,
    svc_004,
    svc_006,
    svc_008,
    svc_013,
    svc_014,
)
from app.services.mvp import AgentApiMvpService
from app.services.wiki_graph import WikiGraphService
from app.services.wiki_documents import WikiDocumentService
from app.services.interests import InterestService
from app.services.generated_content import GeneratedContentService

router = APIRouter(tags=["service-api"])
UserId = Annotated[str, Path(min_length=1, max_length=128, description="사용자 ID")]


def _request_id(request: Request) -> str:
    """추적 미들웨어가 생성한 Request ID를 반환한다."""
    return request.state.request_id


@router.put(
    "/users/{user_id}/context",
    response_model=UserContextResponse,
    operation_id="svc_001",
    summary="사용자 컨텍스트 반영",
)
async def upsert_user_context(
    user_id: UserId,
    payload: UserContextUpsertRequest,
    request: Request,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> UserContextResponse:
    """[SVC-001] Service의 최신 사용자 설정을 Agent 컨텍스트에 반영한다."""
    request_id = _request_id(request)
    return await svc_001(service, user_id, payload, request_id)


@router.post(
    "/users/{user_id}/wiki-sources/clippings",
    response_model=AcceptedJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="svc_002",
    summary="웹 클리핑 처리 요청",
)
async def request_web_clipping(
    user_id: UserId,
    payload: WebClippingRequest,
    request: Request,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> AcceptedJobResponse:
    """[SVC-002] 웹 클리핑을 Personal Wiki Builder Job으로 등록한다."""
    request_id = _request_id(request)
    return await svc_002(
        service,
        user_id=user_id,
        payload=payload,
        request_id=request_id,
    )


@router.post(
    "/users/{user_id}/wiki-sources/urls",
    response_model=AcceptedJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="svc_003",
    summary="URL Wiki 원천 처리 요청",
)
async def request_url_wiki_source(
    user_id: UserId,
    payload: UrlWikiSourceRequest,
    request: Request,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> AcceptedJobResponse:
    """[SVC-003] 사용자 입력 URL을 Personal Wiki Builder Job으로 등록한다."""
    request_id = _request_id(request)
    return await svc_003(
        service,
        user_id=user_id,
        payload=payload,
        request_id=request_id,
    )


@router.post(
    "/users/{user_id}/wiki-sources/content-marks",
    response_model=AcceptedJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="svc_004",
    summary="생성 콘텐츠 위키마킹 요청",
)
async def request_content_mark(
    user_id: UserId,
    payload: ContentMarkRequest,
    request: Request,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> AcceptedJobResponse:
    """[SVC-004] 사용자가 선택한 생성 콘텐츠를 Wiki Build Job으로 등록한다."""
    return await svc_004(
        service,
        user_id=user_id,
        payload=payload,
        request_id=_request_id(request),
    )


@router.post(
    "/users/{user_id}/feedback-signals",
    response_model=FeedbackSignalsResponse,
    operation_id="svc_006",
    summary="사용자 피드백 신호 전달",
)
async def submit_feedback_signals(
    user_id: UserId,
    payload: FeedbackSignalsRequest,
    request: Request,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> FeedbackSignalsResponse:
    """[SVC-006] 좋아요·숨김·신고 신호를 관심사 반영 이벤트로 접수한다.

    Wiki 문서를 만들지 않으며, 다음 관심사 재계산 때 점수에 반영된다.
    """
    return await svc_006(
        service,
        user_id=user_id,
        payload=payload,
        request_id=_request_id(request),
    )


@router.get(
    "/users/{user_id}/wiki/graph",
    response_model=WikiGraphResponse,
    operation_id="pwiki_003",
    summary="개인 Wiki Graph 조회",
)
async def get_personal_wiki_graph(
    user_id: UserId,
    request: Request,
    service: WikiGraphService = Depends(get_wiki_graph_service),
) -> WikiGraphResponse:
    """[PWIKI-003] 현재 Entity·Concept 문서와 관계 Graph를 조회한다."""
    return await service.get_graph(user_id, _request_id(request))


@router.get(
    "/users/{user_id}/wiki/graph/top-nodes",
    response_model=WikiTopNodesResponse,
    operation_id="pwiki_003_top_nodes",
    summary="개인 Wiki 연결 상위 Node 조회",
)
async def list_top_connected_wiki_nodes(
    user_id: UserId,
    request: Request,
    limit: Annotated[
        int, Query(ge=1, le=100, description="반환할 최대 Node 수")
    ] = 10,
    service: WikiGraphService = Depends(get_wiki_graph_service),
) -> WikiTopNodesResponse:
    """[PWIKI-003] 연결 Edge가 많은 순서대로 Entity·Concept Node를 조회한다."""
    return await service.get_top_nodes(user_id, _request_id(request), limit=limit)


@router.get(
    "/users/{user_id}/wiki/documents",
    response_model=WikiDocumentListResponse,
    operation_id="pwiki_003_list",
    summary="개인 Wiki 문서 목록 조회",
)
async def list_personal_wiki_documents(
    user_id: UserId,
    document_kind: Annotated[
        Literal["document", "entity", "concept", "schema"] | None,
        Query(description="필터링할 Wiki 문서 종류"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    service: WikiDocumentService = Depends(get_wiki_document_service),
) -> WikiDocumentListResponse:
    """[PWIKI-003] 사용자 Namespace의 현재 Wiki 문서 목록을 조회한다."""
    return await service.list_documents(
        user_id,
        document_kind=document_kind,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/users/{user_id}/wiki/documents/{document_id}",
    response_model=WikiDocumentDetailResponse,
    operation_id="pwiki_003_detail",
    summary="개인 Wiki 문서 상세 조회",
)
async def get_personal_wiki_document(
    user_id: UserId,
    document_id: Annotated[
        str, Path(min_length=1, max_length=128, description="Wiki 문서 UUID")
    ],
    service: WikiDocumentService = Depends(get_wiki_document_service),
) -> WikiDocumentDetailResponse:
    """[PWIKI-003] 현재 Wiki 문서 Markdown, 출처와 관계를 조회한다."""
    return await service.get_document(user_id, document_id)


@router.get(
    "/users/{user_id}/wiki/versions/{wiki_version_id}",
    response_model=WikiBuildDetailResponse,
    operation_id="pwiki_006_detail",
    summary="개인 Wiki Build 상세 조회",
)
async def get_personal_wiki_version(
    user_id: UserId,
    wiki_version_id: Annotated[
        str, Path(min_length=1, max_length=128, description="Wiki Build UUID")
    ],
    service: WikiDocumentService = Depends(get_wiki_document_service),
) -> WikiBuildDetailResponse:
    """[PWIKI-006] 특정 Build에 고정된 문서 Version 구성을 조회한다."""
    return await service.get_wiki_version(user_id, wiki_version_id)


@router.get(
    "/users/{user_id}/interests",
    response_model=InterestProfileResponse,
    operation_id="int_001_get",
    summary="활성 관심 키워드 조회",
)
async def get_active_interests(
    user_id: UserId,
    service: InterestService = Depends(get_interest_service),
) -> InterestProfileResponse:
    """[INT-001] 개인 Wiki에서 계산된 활성 관심 Topic을 조회한다."""
    return await service.get_active(user_id)


@router.post(
    "/users/{user_id}/interest-profiles/rebuild",
    response_model=InterestProfileResponse,
    operation_id="int_011_rebuild",
    summary="관심 키워드 재계산",
)
async def rebuild_interest_profile(
    user_id: UserId,
    payload: InterestRebuildRequest,
    service: InterestService = Depends(get_interest_service),
) -> InterestProfileResponse:
    """[INT-011] 활성 개인 Wiki에서 관심 키워드를 재계산해 새 Profile로 활성화한다.

    Wiki Build 완료 시 자동 재계산되므로 평시에는 호출할 필요가 없다.
    사용자 "관심사 새로고침" UX와 운영 복구를 위한 수동 경로다.
    """
    return await service.rebuild(user_id, limit=payload.limit)


@router.get(
    "/users/{user_id}/generated-contents",
    response_model=GeneratedContentListResponse,
    operation_id="report_018_list",
    summary="Report Builder 생성 콘텐츠 목록 조회",
)
async def list_generated_contents(
    user_id: UserId,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    service: GeneratedContentService = Depends(get_generated_content_service),
) -> GeneratedContentListResponse:
    """[REPORT-018] 사용자의 저장된 Report Builder 생성 후보를 최신순으로 조회한다."""
    return await service.list_contents(user_id, limit=limit, offset=offset)


@router.get(
    "/users/{user_id}/generated-contents/{candidate_id}",
    response_model=GeneratedContentDetailResponse,
    operation_id="report_018_detail",
    summary="Report Builder 생성 콘텐츠 상세 조회",
)
async def get_generated_content(
    user_id: UserId,
    candidate_id: Annotated[
        str, Path(min_length=1, max_length=128, description="생성 후보 UUID")
    ],
    service: GeneratedContentService = Depends(get_generated_content_service),
) -> GeneratedContentDetailResponse:
    """[REPORT-018] 생성 본문, 실행 정보와 Citation을 조회한다."""
    return await service.get_content(user_id, candidate_id)


@router.post(
    "/users/{user_id}/generations",
    response_model=AcceptedJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="svc_008",
    summary="개인화 콘텐츠 생성 요청",
)
async def request_generation(
    user_id: UserId,
    payload: GenerationRequest,
    request: Request,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> AcceptedJobResponse:
    """[SVC-008] 리포트 생성기 개인화 콘텐츠 생성 Job을 등록한다."""
    request_id = _request_id(request)
    return await svc_008(
        service,
        user_id=user_id,
        payload=payload,
        request_id=request_id,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    operation_id="svc_013",
    summary="Agent Job 상태 조회",
)
async def get_job_status(
    job_id: Annotated[str, Path(min_length=1, max_length=128)],
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> JobStatusResponse:
    """[SVC-013] Agent Job의 현재 상태와 진행률을 조회한다."""
    return await svc_013(service, job_id)


@router.get(
    "/jobs/{job_id}/result",
    response_model=JobResultResponse,
    operation_id="svc_014",
    summary="Agent Job 결과 조회",
)
async def get_job_result(
    job_id: Annotated[str, Path(min_length=1, max_length=128)],
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> JobResultResponse:
    """[SVC-014] 완료된 Agent Job의 기능별 결과를 조회한다."""
    return await svc_014(service, job_id)
