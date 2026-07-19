"""Swagger에서 실제 Agent Job을 즉시 실행하는 개발 전용 라우터.

local 또는 test 환경에서 설정으로 명시적으로 활성화했을 때만 최상위
Router에 포함되며, 운영 비동기 API가 등록한 Job Handler를 그대로 호출한다.
"""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Request, status

from app.dependencies import (
    AppContainer,
    get_agent_workflow_service,
    get_container,
    get_development_scenario_service,
    get_interest_service,
    get_latest_information_service,
    get_mvp_service,
)
from app.exceptions import AgentApiError, ErrorDetail
from app.schemas.development import (
    DevelopmentJobRunResponse,
    SourceToContentScenarioRequest,
    SourceToContentScenarioResponse,
    WikiBuildRunRequest,
)
from app.schemas.interests import InterestProfileResponse, InterestRebuildRequest
from app.schemas.latest_information import (
    LatestInformationSearchRequest,
    LatestInformationSearchResponse,
)
from app.schemas.mvp import GenerationRequest
from app.services.agent_workflows import AgentWorkflowService
from app.services.interests import InterestService
from app.services.latest_information import LatestInformationService
from app.services.mvp import AgentApiMvpService
from app.services.development_scenarios import DevelopmentScenarioService


async def require_development_access(
    container: AppContainer = Depends(get_container),
    dev_token: Annotated[
        str | None,
        Header(alias="X-Dev-Token", description="설정된 개발 API 보호 토큰"),
    ] = None,
) -> None:
    """개발 API 활성 환경과 선택 보호 토큰을 다시 확인한다."""
    settings = container.settings
    if not settings.dev_agent_api_enabled:
        raise AgentApiError(
            status.HTTP_404_NOT_FOUND,
            ErrorDetail(code="DEV_API_DISABLED", message="개발 API가 비활성화되었습니다."),
        )
    expected = settings.dev_agent_api_token
    if expected is not None and (
        dev_token is None
        or not secrets.compare_digest(expected.get_secret_value(), dev_token)
    ):
        raise AgentApiError(
            status.HTTP_401_UNAUTHORIZED,
            ErrorDetail(
                code="INVALID_DEV_TOKEN",
                message="개발 API 토큰이 올바르지 않습니다.",
            ),
        )


router = APIRouter(dependencies=[Depends(require_development_access)])
JobId = Annotated[str, Path(min_length=1, max_length=128, description="Agent Job ID")]
UserId = Annotated[str, Path(min_length=1, max_length=128, description="사용자 ID")]


@router.post(
    "/jobs/{job_id}/run",
    response_model=DevelopmentJobRunResponse,
    tags=["dev-jobs"],
    operation_id="dev_run_job",
    summary="Agent Job 즉시 실행",
)
async def run_agent_job(
    job_id: JobId,
    service: AgentWorkflowService = Depends(get_agent_workflow_service),
) -> DevelopmentJobRunResponse:
    """등록된 URL 수집 또는 Personal Wiki Build Job을 즉시 실행한다."""
    return await service.run_job(job_id)


@router.post(
    "/users/{user_id}/wiki-builds",
    response_model=DevelopmentJobRunResponse,
    tags=["dev-wiki"],
    operation_id="dev_run_wiki_build",
    summary="Personal Wiki Builder 즉시 실행",
)
async def run_personal_wiki_build(
    user_id: UserId,
    payload: WikiBuildRunRequest,
    service: AgentWorkflowService = Depends(get_agent_workflow_service),
) -> DevelopmentJobRunResponse:
    """사용자의 Personal Wiki Build Job만 유형과 소유자를 검증해 실행한다."""
    return await service.run_job(
        payload.job_id,
        expected_job_type="personal_wiki_build",
        expected_user_id=user_id,
    )


@router.post(
    "/users/{user_id}/interest-profiles/rebuild",
    response_model=InterestProfileResponse,
    tags=["dev-interests"],
    operation_id="dev_rebuild_interests",
    summary="관심 키워드 즉시 재계산",
)
async def rebuild_interest_profile(
    user_id: UserId,
    payload: InterestRebuildRequest,
    service: InterestService = Depends(get_interest_service),
) -> InterestProfileResponse:
    """현재 활성 Wiki에서 관심 키워드·점수·근거를 계산해 새 Profile로 저장한다."""
    return await service.rebuild(user_id, limit=payload.limit)


@router.post(
    "/users/{user_id}/latest-information/search",
    response_model=LatestInformationSearchResponse,
    tags=["dev-global"],
    operation_id="dev_search_latest_information",
    summary="최신 외부 정보 수집·검색",
)
async def search_latest_information(
    user_id: UserId,
    payload: LatestInformationSearchRequest,
    service: LatestInformationService = Depends(get_latest_information_service),
) -> LatestInformationSearchResponse:
    """직접 또는 활성 관심 키워드로 최신 자료를 수집해 Global 문서로 저장한다."""
    return await service.search(user_id, payload)


@router.post(
    "/users/{user_id}/bambi-generations",
    response_model=DevelopmentJobRunResponse,
    tags=["dev-bambi"],
    operation_id="dev_run_bambi_generation",
    summary="Bambi 콘텐츠 즉시 생성",
)
async def run_bambi_generation(
    user_id: UserId,
    payload: GenerationRequest,
    request: Request,
    jobs: AgentApiMvpService = Depends(get_mvp_service),
    workflows: AgentWorkflowService = Depends(get_agent_workflow_service),
) -> DevelopmentJobRunResponse:
    """Bambi Job을 멱등 등록하고 개인·Global 검색부터 저장까지 즉시 실행한다."""
    accepted = await jobs.submit_generation(
        user_id=user_id,
        payload=payload,
        request_id=request.state.request_id,
    )
    return await workflows.run_job(
        accepted.job_id,
        expected_job_type="bambi_generation",
        expected_user_id=user_id,
    )


@router.post(
    "/users/{user_id}/scenarios/source-to-content",
    response_model=SourceToContentScenarioResponse,
    tags=["dev-scenarios"],
    operation_id="dev_run_source_to_content_scenario",
    summary="원본에서 Bambi 콘텐츠까지 전체 실행",
)
async def run_source_to_content_scenario(
    user_id: UserId,
    payload: SourceToContentScenarioRequest,
    request: Request,
    service: DevelopmentScenarioService = Depends(
        get_development_scenario_service
    ),
) -> SourceToContentScenarioResponse:
    """URL·클리핑 저장부터 Wiki·관심·최신 정보·Bambi 저장까지 실행한다."""
    return await service.run(
        user_id,
        payload,
        request_id=request.state.request_id,
    )
