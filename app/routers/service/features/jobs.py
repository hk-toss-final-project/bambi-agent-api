"""Service Agent Job 상태와 결과 조회 기능 구현."""

from typing import Protocol

from app.schemas.mvp import JobResultResponse, JobStatusBatchResponse, JobStatusResponse


class JobQueryService(Protocol):
    """Agent Job 조회에 필요한 애플리케이션 서비스 경계."""

    async def get_job(self, job_id: str) -> JobStatusResponse:
        """Agent Job의 현재 상태를 조회한다."""
        ...

    async def get_jobs(self, job_ids: list[str]) -> JobStatusBatchResponse:
        """여러 Agent Job의 현재 상태를 조회한다."""
        ...

    async def get_job_result(self, job_id: str) -> JobResultResponse:
        """완료된 Agent Job의 결과를 조회한다."""
        ...


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_013(service: JobQueryService, job_id: str) -> JobStatusResponse:
    """[SVC-013] Agent Job 상태 조회.

    비동기 작업 상태를 조회한다.
    """
    return await service.get_job(job_id)


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_014(service: JobQueryService, job_id: str) -> JobResultResponse:
    """[SVC-014] Agent 결과 조회.

    생성 및 처리 결과를 Agent API에서 조회한다.
    """
    return await service.get_job_result(job_id)


# MVP: agent-api-mvp-scope.md에서 구현 대상으로 지정된 기능입니다.
async def svc_015(
    service: JobQueryService, job_ids: list[str]
) -> JobStatusBatchResponse:
    """[SVC-015] Agent Job 상태 Batch 조회.

    Service Worker가 활성 작업 여러 건의 상태를 한 번에 조회한다.
    """
    return await service.get_jobs(job_ids)
