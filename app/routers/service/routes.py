"""Service API가 호출하는 FastAPI MVP 내부 라우터."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, Query, Request, status

from app.exceptions import AgentApiError, ErrorDetail
from app.dependencies import (
    get_briefing_topics_service,
    get_collection_schedule_service,
    get_mvp_service,
    get_interest_service,
    get_generated_content_service,
    get_wiki_document_service,
    get_wiki_graph_service,
    get_wiki_navigator_service,
    get_mcp_api_key_service,
)
from app.schemas.collection_schedules import (
    CollectionScheduleListResponse,
    CollectionScheduleRegisterRequest,
    CollectionScheduleResponse,
    CollectionScheduleRunAcceptedResponse,
    CollectionScheduleUpdateRequest,
)
from app.schemas.generated_content import (
    GeneratedContentDetailResponse,
    GeneratedContentListResponse,
)
from app.schemas.interests import InterestProfileResponse, InterestRebuildRequest
from app.schemas.interest_taxonomy import (
    InterestTaxonomyResponse,
    InterestTaxonomyUpsertRequest,
)
from app.schemas.mvp import (
    AcceptedJobResponse,
    ContentMarkDeletionRequest,
    ContentMarkRequest,
    FeedbackSignalsRequest,
    FeedbackSignalsResponse,
    GenerationRequest,
    JobResultResponse,
    JobStatusBatchRequest,
    JobStatusBatchResponse,
    JobStatusResponse,
    PersonalWikiResetResponse,
    UrlWikiSourceRequest,
    UserContextResponse,
    UserContextUpsertRequest,
    WebClippingRequest,
    WikiDocumentDeletionResponse,
    WikiSourceDeletionRequest,
)
from app.schemas.mcp_api_keys import (
    McpApiKeyCreateRequest,
    McpApiKeyCreateResponse,
    McpApiKeyListResponse,
    McpApiKeyResponse,
)
from app.schemas.wiki import (
    WikiBuildDetailResponse,
    WikiDocumentDetailResponse,
    WikiDocumentListResponse,
    WikiGraphResponse,
    WikiTopNodesResponse,
)
from app.schemas.wiki_navigation import WikiNavigateRequest, WikiNavigateResponse
from app.security.internal_auth.api import require_service_api_access
from app.routers.service.api import (
    svc_001,
    svc_002,
    svc_003,
    svc_004,
    svc_004_delete,
    svc_006,
    svc_008,
    svc_013,
    svc_014,
    svc_015,
)
from app.services.collection_schedules import CollectionScheduleService
from app.services.mvp import AgentApiMvpService
from agent.report_builder.api import DEFAULT_BRIEFING_TOPIC_COUNT
from app.schemas.briefing_topics import (
    BriefingPreparationRequest,
    BriefingTopicsResponse,
)
from app.services.briefing_topics import BriefingTopicsService
from app.services.wiki_graph import WikiGraphService
from app.services.wiki_navigator import WikiNavigatorService
from app.services.wiki_documents import WikiDocumentService
from app.services.interests import InterestService
from app.services.generated_content import GeneratedContentService
from app.services.mcp_api_keys import McpApiKeyService

router = APIRouter(
    tags=["service-api"],
    dependencies=[Depends(require_service_api_access)],
)
UserId = Annotated[str, Path(min_length=1, max_length=128, description="사용자 ID")]
KST = ZoneInfo("Asia/Seoul")


def _request_id(request: Request) -> str:
    """추적 미들웨어가 생성한 Request ID를 반환한다."""
    return request.state.request_id


@router.post(
    "/users/{user_id}/mcp-api-keys",
    response_model=McpApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="key_001",
    summary="MCP Personal Access Token 발급",
)
async def create_mcp_api_key(
    user_id: UserId,
    payload: McpApiKeyCreateRequest,
    request: Request,
    service: McpApiKeyService = Depends(get_mcp_api_key_service),
) -> McpApiKeyCreateResponse:
    """[KEY-001] 사용자 Wiki 읽기 전용 MCP API Key를 발급한다."""
    return await service.create(user_id, payload, request_id=_request_id(request))


@router.get(
    "/users/{user_id}/mcp-api-keys",
    response_model=McpApiKeyListResponse,
    operation_id="key_002",
    summary="MCP Personal Access Token 목록 조회",
)
async def list_mcp_api_keys(
    user_id: UserId,
    service: McpApiKeyService = Depends(get_mcp_api_key_service),
) -> McpApiKeyListResponse:
    """[KEY-002] 원문과 Hash를 제외한 사용자 API Key 목록을 조회한다."""
    return await service.list(user_id)


@router.delete(
    "/users/{user_id}/mcp-api-keys/{key_id}",
    response_model=McpApiKeyResponse,
    operation_id="key_005",
    summary="MCP Personal Access Token 폐기",
)
async def revoke_mcp_api_key(
    user_id: UserId,
    key_id: Annotated[UUID, Path(description="MCP API Key UUID")],
    request: Request,
    service: McpApiKeyService = Depends(get_mcp_api_key_service),
) -> McpApiKeyResponse:
    """[KEY-005] 사용자 소유 MCP API Key를 영구 폐기한다."""
    return await service.revoke(user_id, str(key_id), request_id=_request_id(request))


@router.put(
    "/interest-taxonomies/{version}",
    response_model=InterestTaxonomyResponse,
    operation_id="upsert_interest_taxonomy",
    summary="관심사 taxonomy Snapshot 반영",
)
async def upsert_interest_taxonomy(
    version: Annotated[str, Path(min_length=1, max_length=50)],
    payload: InterestTaxonomyUpsertRequest,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> InterestTaxonomyResponse:
    """Service DB의 taxonomy를 Agent DB에 버전 단위로 복제한다."""
    if version != payload.version:
        raise AgentApiError(
            status.HTTP_409_CONFLICT,
            ErrorDetail(
                code="INTEREST_TAXONOMY_VERSION_MISMATCH",
                message="경로와 본문의 taxonomy 버전이 다릅니다.",
            ),
        )
    return await service.upsert_interest_taxonomy(payload)


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
    summary="리포트 북마크 위키 편입 요청",
)
async def request_content_mark(
    user_id: UserId,
    payload: ContentMarkRequest,
    request: Request,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> AcceptedJobResponse:
    """[SVC-004] 사용자가 북마크한 리포트(작성자 무관)를 Wiki Build Job으로 등록한다."""
    return await svc_004(
        service,
        user_id=user_id,
        payload=payload,
        request_id=_request_id(request),
    )


@router.post(
    "/users/{user_id}/wiki-sources/content-marks/deletions",
    response_model=AcceptedJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="svc_004_delete",
    summary="리포트 북마크 Wiki 연결 해제 요청",
)
async def request_content_mark_deletion(
    user_id: UserId,
    payload: ContentMarkDeletionRequest,
    request: Request,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> AcceptedJobResponse:
    """[SVC-004] 북마크 연결을 해제하고 활성 원본 기준 재빌드 Job을 등록한다."""
    return await svc_004_delete(
        service,
        user_id=user_id,
        payload=payload,
        request_id=_request_id(request),
    )


@router.post(
    "/users/{user_id}/wiki-sources/deletions",
    response_model=WikiDocumentDeletionResponse,
    operation_id="wba_015_delete",
    summary="개인 Wiki 문서 삭제",
)
async def delete_wiki_document(
    user_id: UserId,
    payload: WikiSourceDeletionRequest,
    request: Request,
    service: WikiDocumentService = Depends(get_wiki_document_service),
) -> WikiDocumentDeletionResponse:
    """[WBA-015] delete 이벤트를 기록하고 문서를 soft-delete한다 (동기, 멱등).

    Chunk는 즉시 검색에서 제외된다. 같은 개념이 새 클리핑으로 재등장하면
    새 문서로 되살아난다(D1 잠정: 기본 부활 — tombstone 옵션은 팀 결정 후).
    관심사 반영이 급하면 재계산 API를 이어서 호출한다.
    """
    return await service.delete_document(
        user_id, payload, request_id=_request_id(request)
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

    Wiki 문서를 만들지 않으며 저장 직후 관심사 재계산을 best-effort로 시도한다.
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


@router.post(
    "/users/{user_id}/wiki/navigate",
    response_model=WikiNavigateResponse,
    operation_id="wnav_006",
    summary="개인 LLM Wiki 탐색",
)
async def navigate_personal_wiki(
    user_id: UserId,
    payload: WikiNavigateRequest,
    service: WikiNavigatorService = Depends(get_wiki_navigator_service),
) -> WikiNavigateResponse:
    """[WNAV-006] 후보 또는 선택 Page의 출처 포함 Context Packet을 반환한다."""
    return await service.navigate(user_id, payload)


@router.delete(
    "/users/{user_id}/wiki",
    response_model=PersonalWikiResetResponse,
    operation_id="pwiki_013",
    summary="개인 LLM Wiki 초기화",
)
async def reset_personal_wiki(
    user_id: UserId,
    request: Request,
    service: WikiDocumentService = Depends(get_wiki_document_service),
) -> PersonalWikiResetResponse:
    """[PWIKI-013] 사용자 원본을 영구 삭제하고 개인 LLM Wiki를 초기화한다."""
    return await service.reset_wiki(user_id, request_id=_request_id(request))


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
    "/users/{user_id}/briefing-topics",
    response_model=BriefingTopicsResponse,
    operation_id="report_briefing_topics",
    summary="아침 브리핑 주제 선정",
)
async def select_morning_briefing_topics(
    user_id: UserId,
    briefing_date: Annotated[
        date | None,
        Query(description="조회할 KST 기준 브리핑 날짜. 생략하면 오늘"),
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=5, description="고를 주제 수")
    ] = DEFAULT_BRIEFING_TOPIC_COUNT,
    service: BriefingTopicsService = Depends(get_briefing_topics_service),
) -> BriefingTopicsResponse:
    """준비 Worker가 저장한 아침 브리핑 주제를 LLM 호출 없이 조회한다.

    Service는 이 결과를 아침 생성 요청의 `topics[]`에 넣는다. 연결 수 상위 3개를
    그대로 쓰면 도구·출처가 주제가 되므로(실측: `DBeaver Community` 1.00),
    후보를 넓게 받아 맥락을 읽고 고른다. 준비 Snapshot이 없으면 빈 목록을
    반환해 Service가 등록 관심사 폴백을 사용하게 한다.
    """
    resolved_date = briefing_date or datetime.now(KST).date()
    return await service.get_topics(
        user_id,
        briefing_date=resolved_date,
        limit=limit,
    )


@router.post(
    "/users/{user_id}/briefing-preparations",
    response_model=AcceptedJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="report_022",
    summary="아침 브리핑 주제·근거 준비 요청",
)
async def prepare_morning_briefing(
    user_id: UserId,
    payload: BriefingPreparationRequest,
    request: Request,
    service: BriefingTopicsService = Depends(get_briefing_topics_service),
) -> AcceptedJobResponse:
    """[REPORT-022] 날짜별 주제 선정과 근거 예열을 비동기 Job으로 등록한다."""
    return await service.enqueue_preparation(
        user_id,
        payload,
        request_id=_request_id(request),
    )


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


@router.post(
    "/jobs/statuses",
    response_model=JobStatusBatchResponse,
    operation_id="svc_015",
    summary="Agent Job 상태 Batch 조회",
)
async def get_job_statuses(
    payload: JobStatusBatchRequest,
    service: AgentApiMvpService = Depends(get_mvp_service),
) -> JobStatusBatchResponse:
    """[SVC-015] 활성 Agent Job 여러 건의 현재 상태를 한 번에 조회한다."""
    return await svc_015(service, payload.job_ids)


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


SourceKey = Annotated[
    str,
    Path(min_length=1, max_length=128, description="수집 Source 식별 Key"),
]


@router.get(
    "/collection-schedules",
    response_model=CollectionScheduleListResponse,
    operation_id="sch_022",
    summary="수집 스케줄 목록·실행 이력 조회",
    description=(
        "Agent가 돌리는 Global 수집 스케줄의 현재 설정과 최근 실행 이력을 "
        "반환한다. 주기가 아직 없거나 중지된 Source도 함께 보여 준다."
    ),
)
async def list_collection_schedules(
    source_key: Annotated[
        str | None, Query(description="특정 Source만 조회할 때 지정")
    ] = None,
    history_limit: Annotated[
        int, Query(ge=1, le=200, description="함께 반환할 최근 실행 이력 건수")
    ] = 20,
    service: CollectionScheduleService = Depends(get_collection_schedule_service),
) -> CollectionScheduleListResponse:
    """[SCH-022] 수집 스케줄별 실행 결과와 상태를 조회한다."""
    return await service.list_schedules(
        source_key=source_key, history_limit=history_limit
    )


@router.post(
    "/collection-schedules",
    response_model=CollectionScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="sch_017",
    summary="수집 스케줄 등록",
    description=(
        "정기 수집 주기를 등록한다. 같은 source_key로 다시 등록하면 설정을 "
        "덮어쓰고 중지 상태였더라도 다시 활성화한다(멱등). keywords는 각각 "
        "따로 검색하므로 주제를 한 문자열에 합치지 않는다."
    ),
)
async def register_collection_schedule(
    payload: CollectionScheduleRegisterRequest,
    service: CollectionScheduleService = Depends(get_collection_schedule_service),
) -> CollectionScheduleResponse:
    """[SCH-017] 새로운 정기 수집 작업을 등록한다."""
    return await service.register(payload)


@router.patch(
    "/collection-schedules/{source_key}",
    response_model=CollectionScheduleResponse,
    operation_id="sch_018",
    summary="수집 스케줄 수정",
    description=(
        "등록된 수집 스케줄에서 넘긴 항목만 변경한다. 변경은 Scheduler의 다음 "
        "확인 주기부터 반영되며 서버 재시작이 필요 없다."
    ),
)
async def update_collection_schedule_route(
    source_key: SourceKey,
    payload: CollectionScheduleUpdateRequest,
    service: CollectionScheduleService = Depends(get_collection_schedule_service),
) -> CollectionScheduleResponse:
    """[SCH-018] 기존 수집 작업의 실행 주기를 변경한다."""
    return await service.update(source_key, payload)


@router.post(
    "/collection-schedules/{source_key}/run",
    response_model=CollectionScheduleRunAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="sch_021",
    summary="수집 스케줄 즉시 실행",
    description=(
        "등록된 Cron 주기를 기다리지 않고 지금 수집하도록 **백그라운드 Job으로 "
        "예약**하고 바로 응답한다(202). 키워드를 바꾼 직후 실제로 적재되는지 "
        "확인할 때 쓴다.\n\n"
        "- **정기 실행 조건에 걸리지 않는다.** Cron 주기·일일 실행 한도"
        "(`daily_max_runs`)·중지(paused) 상태를 모두 건너뛰고 등록된 검색을 "
        "전부 수집한다.\n"
        "- **수집은 정기 수집과 같은 경로를 Scheduler가 대신 돌린다.** 관심 "
        "Topic이 많은 taxonomy Source는 수집이 수 분 걸리므로, 동기로 기다리지 "
        "않고 Job으로 넘겨 응답이 타임아웃되지 않게 한다.\n"
        "- 응답의 `job_id`로 `GET /jobs/{job_id}`에서 진행 상태와 결과 요약"
        "(수집·저장 건수)을 확인한다. 실행 이력은 `GET /collection-schedules`"
        "에도 남는다.\n"
        "- 수집한 기사는 본문 없이 `pending` 상태로 저장된다. 본문은 이후 본문 "
        "수집 Worker(`global-content`)가 채운다."
    ),
)
async def run_collection_schedule_now(
    source_key: SourceKey,
    request: Request,
    service: CollectionScheduleService = Depends(get_collection_schedule_service),
) -> CollectionScheduleRunAcceptedResponse:
    """[SCH-021] 등록된 정기 수집 작업을 주기와 무관하게 즉시 실행하도록 예약한다."""
    return await service.run_now(source_key, request_id=_request_id(request))


@router.post(
    "/collection-schedules/{source_key}/pause",
    response_model=CollectionScheduleResponse,
    operation_id="sch_019",
    summary="수집 스케줄 중지",
)
async def pause_collection_schedule(
    source_key: SourceKey,
    service: CollectionScheduleService = Depends(get_collection_schedule_service),
) -> CollectionScheduleResponse:
    """[SCH-019] 정기 수집 실행을 일시 중지한다. 설정은 그대로 보존한다."""
    return await service.pause(source_key)


@router.post(
    "/collection-schedules/{source_key}/resume",
    response_model=CollectionScheduleResponse,
    operation_id="sch_020",
    summary="수집 스케줄 재개",
)
async def resume_collection_schedule(
    source_key: SourceKey,
    service: CollectionScheduleService = Depends(get_collection_schedule_service),
) -> CollectionScheduleResponse:
    """[SCH-020] 중지된 정기 수집 작업을 다시 활성화한다."""
    return await service.resume(source_key)
