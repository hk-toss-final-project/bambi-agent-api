"""Service API가 호출하는 FastAPI MVP 내부 라우터."""

from typing import Annotated, Literal, TypeVar, cast

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
from app.schemas.interests import InterestProfileResponse
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
    svc_008,
    svc_013,
    svc_014,
)
from app.services.mvp import AgentApiMvpService
from app.services.wiki_graph import WikiGraphService
from app.services.wiki_documents import WikiDocumentService
from app.services.interests import InterestService
from app.services.generated_content import GeneratedContentService
from shared.contracts import FeatureRequest, FeatureResult

router = APIRouter(tags=["service-api"])
UserId = Annotated[str, Path(min_length=1, max_length=128, description="사용자 ID")]
ResponseT = TypeVar("ResponseT")


def _request_id(request: Request) -> str:
    """추적 미들웨어가 생성한 Request ID를 반환한다."""
    return request.state.request_id


def _feature_response(
    result: FeatureResult,
    response_type: type[ResponseT],
) -> ResponseT:
    """기능 결과에 담긴 FastAPI 응답 객체를 타입 검증해 반환한다."""
    response = result.data.get("result")
    if not isinstance(response, response_type):
        raise RuntimeError(
            f"{result.feature_id}가 예상 응답 {response_type.__name__}을 반환하지 않았습니다."
        )
    return cast(ResponseT, response)


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
    result = await svc_001(
        FeatureRequest(
            request_id=request_id,
            actor_id="service-api",
            user_id=user_id,
            payload={
                "implementation": lambda: service.upsert_user_context(
                    user_id, payload, request_id
                )
            },
        )
    )
    return _feature_response(result, UserContextResponse)


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
    result = await svc_002(
        FeatureRequest(
            request_id=request_id,
            actor_id="service-api",
            user_id=user_id,
            payload={
                "implementation": lambda: service.submit_web_clipping(
                    user_id=user_id,
                    payload=payload,
                    request_id=request_id,
                )
            },
        )
    )
    return _feature_response(result, AcceptedJobResponse)


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
    result = await svc_003(
        FeatureRequest(
            request_id=request_id,
            actor_id="service-api",
            user_id=user_id,
            payload={
                "implementation": lambda: service.submit_url_source(
                    user_id=user_id,
                    payload=payload,
                    request_id=request_id,
                )
            },
        )
    )
    return _feature_response(result, AcceptedJobResponse)


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
    """[SVC-004] 위키마킹 접수. 처리 Handler 구현 전까지 501을 반환한다."""
    return await service.submit_content_mark(
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


@router.get(
    "/users/{user_id}/generated-contents",
    response_model=GeneratedContentListResponse,
    operation_id="bambi_018_list",
    summary="Bambi 생성 콘텐츠 목록 조회",
)
async def list_generated_contents(
    user_id: UserId,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    service: GeneratedContentService = Depends(get_generated_content_service),
) -> GeneratedContentListResponse:
    """[BAMBI-018] 사용자의 저장된 Bambi 생성 후보를 최신순으로 조회한다."""
    return await service.list_contents(user_id, limit=limit, offset=offset)


@router.get(
    "/users/{user_id}/generated-contents/{candidate_id}",
    response_model=GeneratedContentDetailResponse,
    operation_id="bambi_018_detail",
    summary="Bambi 생성 콘텐츠 상세 조회",
)
async def get_generated_content(
    user_id: UserId,
    candidate_id: Annotated[
        str, Path(min_length=1, max_length=128, description="생성 후보 UUID")
    ],
    service: GeneratedContentService = Depends(get_generated_content_service),
) -> GeneratedContentDetailResponse:
    """[BAMBI-018] 생성 본문, 실행 정보와 Citation을 조회한다."""
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
    """[SVC-008] 밤비 개인화 콘텐츠 생성 Job을 등록한다."""
    request_id = _request_id(request)
    result = await svc_008(
        FeatureRequest(
            request_id=request_id,
            actor_id="service-api",
            user_id=user_id,
            payload={
                "implementation": lambda: service.submit_generation(
                    user_id=user_id,
                    payload=payload,
                    request_id=request_id,
                )
            },
        )
    )
    return _feature_response(result, AcceptedJobResponse)


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    operation_id="svc_013",
    summary="Agent Job 상태 조회",
)
async def get_job_status(
    job_id: Annotated[str, Path(min_length=1, max_length=128)],
    request: Request,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> JobStatusResponse:
    """[SVC-013] Agent Job의 현재 상태와 진행률을 조회한다."""
    result = await svc_013(
        FeatureRequest(
            request_id=_request_id(request),
            actor_id="service-api",
            payload={"implementation": lambda: service.get_job(job_id)},
        )
    )
    return _feature_response(result, JobStatusResponse)


@router.get(
    "/jobs/{job_id}/result",
    response_model=JobResultResponse,
    operation_id="svc_014",
    summary="Agent Job 결과 조회",
)
async def get_job_result(
    job_id: Annotated[str, Path(min_length=1, max_length=128)],
    request: Request,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> JobResultResponse:
    """[SVC-014] 완료된 Agent Job의 기능별 결과를 조회한다."""
    result = await svc_014(
        FeatureRequest(
            request_id=_request_id(request),
            actor_id="service-api",
            payload={"implementation": lambda: service.get_job_result(job_id)},
        )
    )
    return _feature_response(result, JobResultResponse)
