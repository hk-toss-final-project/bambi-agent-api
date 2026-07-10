"""Liveness, Readiness와 Version을 제공하는 시스템 API 라우터."""

from fastapi import APIRouter, Depends, status

from app.dependencies import AppContainer, get_container
from app.exceptions import AgentApiError, ErrorDetail
from app.schemas.mvp import HealthResponse, VersionResponse

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/live", response_model=HealthResponse, operation_id="sys_009")
async def liveness() -> HealthResponse:
    """[SYS-009] Agent API 프로세스가 요청에 응답할 수 있는지 확인한다."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse, operation_id="sys_010")
async def readiness(
    container: AppContainer = Depends(get_container),
) -> HealthResponse:
    """[SYS-010] 애플리케이션 컴포넌트가 요청 처리 준비 상태인지 확인한다."""
    checks = {
        "container": container.ready,
        "mvp_service": container.mvp_service is not None,
    }
    if not all(checks.values()):
        raise AgentApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorDetail(
                code="SERVICE_NOT_READY",
                message="Agent API가 아직 요청 처리 준비 상태가 아닙니다.",
                retryable=True,
            ),
        )
    return HealthResponse(status="ready", checks=checks)


@router.get("/version", response_model=VersionResponse, operation_id="sys_011")
async def version(container: AppContainer = Depends(get_container)) -> VersionResponse:
    """[SYS-011] Agent API 버전과 실행 환경을 반환한다."""
    settings = container.settings
    return VersionResponse(
        name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )
