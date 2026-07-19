"""개발 API와 운영 Worker가 공유할 Agent Job 실행기.

Job 유형에 따라 URL 수집 또는 Personal Wiki Build Handler를 호출하고,
Lease·완료·실패 상태를 저장한 뒤 Swagger용 단계 결과를 반환한다.
"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from fastapi import status

from app.config import Settings
from app.exceptions import AgentApiError, ErrorDetail
from app.schemas.development import (
    DevelopmentJobRunResponse,
    DevelopmentRunStage,
)
from app.services.agent_jobs import AgentJobRepository, ClaimedJobRecord
from infrastructure.sources.connectors.api import (
    JinaReadError,
    JinaReadResult,
    fetch_url_via_jina,
)

type UrlFetcher = Callable[[str], JinaReadResult]


def _parse_published_at(value: str | None) -> datetime | None:
    """외부 수집기의 ISO 게시 시각을 timezone 포함 datetime으로 변환한다."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class AgentWorkflowService:
    """저장된 Agent Job을 실제 Handler로 한 건씩 실행한다."""

    def __init__(
        self,
        repository: AgentJobRepository,
        settings: Settings,
        *,
        url_fetcher: UrlFetcher = fetch_url_via_jina,
    ) -> None:
        """Job 저장소, 모델 설정과 URL 수집기를 주입한다."""
        self._repository = repository
        self._settings = settings
        self._url_fetcher = url_fetcher

    async def _dispatch(self, job: ClaimedJobRecord) -> tuple[str, dict[str, object]]:
        """Job 유형에 맞는 URL 수집 또는 Wiki Build Handler를 실행한다."""
        if job.job_type == "personal_wiki_url":
            url = str(job.payload.get("url") or "")
            if not url:
                raise ValueError("URL 수집 Job Payload에 url이 없습니다.")
            fetched = await asyncio.to_thread(self._url_fetcher, url)
            result = await self._repository.save_fetched_url(
                job=job,
                title=fetched.title,
                markdown=fetched.markdown,
                resolved_url=fetched.resolved_url,
                published_at=_parse_published_at(fetched.published_time),
            )
            return "url_collection", result
        if job.job_type == "personal_wiki_build":
            result = await self._repository.build_personal_wiki(
                job=job,
                model=self._settings.wiki_llm_model,
            )
            return "wiki_build", result
        if job.job_type == "bambi_generation":
            result = await self._repository.build_bambi_content(
                job=job,
                model=self._settings.bambi_llm_model,
            )
            return "bambi_generation", result
        raise ValueError(f"개발 실행기가 지원하지 않는 Job 유형입니다: {job.job_type}")

    async def run_job(
        self,
        job_id: str,
        *,
        expected_job_type: str | None = None,
        expected_user_id: str | None = None,
    ) -> DevelopmentJobRunResponse:
        """Agent Job 하나를 제한 시간 안에 실행하고 단계별 결과를 반환한다."""
        existing = await self._repository.get_job(job_id)
        if existing is None:
            raise AgentApiError(
                status.HTTP_404_NOT_FOUND,
                ErrorDetail(code="JOB_NOT_FOUND", message="Agent Job을 찾을 수 없습니다."),
            )
        if expected_job_type and existing.job_type != expected_job_type:
            raise AgentApiError(
                status.HTTP_409_CONFLICT,
                ErrorDetail(
                    code="JOB_TYPE_MISMATCH",
                    message=f"{expected_job_type} Job만 이 경로에서 실행할 수 있습니다.",
                ),
            )
        if expected_user_id and existing.user_id != expected_user_id:
            raise AgentApiError(
                status.HTTP_404_NOT_FOUND,
                ErrorDetail(code="JOB_NOT_FOUND", message="Agent Job을 찾을 수 없습니다."),
            )
        started_at = datetime.now(UTC)
        started = monotonic()
        run_id = str(uuid4())
        if existing.status == "completed":
            elapsed = int((monotonic() - started) * 1000)
            return DevelopmentJobRunResponse(
                run_id=run_id,
                job_id=job_id,
                job_type=existing.job_type,
                status="completed",
                started_at=started_at,
                duration_ms=elapsed,
                stages=[
                    DevelopmentRunStage(
                        name="existing_result",
                        status="skipped",
                        duration_ms=0,
                        result=existing.result or {},
                    )
                ],
                result=existing.result or {},
                warnings=["이미 완료된 멱등 Job의 저장 결과를 반환했습니다."],
            )

        worker_id = f"dev-api:{run_id}"
        claimed = await self._repository.claim_job(
            job_id=job_id,
            worker_id=worker_id,
            lease_seconds=self._settings.personal_wiki_job_lease_seconds,
        )
        if claimed is None:
            raise AgentApiError(
                status.HTTP_409_CONFLICT,
                ErrorDetail(
                    code="JOB_NOT_RUNNABLE",
                    message="Job이 실행 가능한 대기 상태가 아니거나 Lease를 점유 중입니다.",
                    retryable=True,
                ),
            )

        stage_name = claimed.job_type
        stage_started = monotonic()
        try:
            async with asyncio.timeout(self._settings.dev_agent_timeout_seconds):
                stage_name, result = await self._dispatch(claimed)
                await self._repository.complete_job(
                    job=claimed,
                    worker_id=worker_id,
                    result=result,
                )
        except Exception as error:
            retryable = isinstance(error, (JinaReadError, TimeoutError))
            if isinstance(error, JinaReadError):
                error_code = f"JINA_{error.error_code.upper()}"
            elif isinstance(error, TimeoutError):
                error_code = "DEV_AGENT_TIMEOUT"
            elif isinstance(error, ValueError):
                error_code = "INVALID_JOB_PAYLOAD"
            else:
                error_code = "AGENT_EXECUTION_FAILED"
            await self._repository.fail_job(
                job=claimed,
                worker_id=worker_id,
                error_code=error_code,
                error_message=str(error),
                retryable=retryable,
            )
            stage_elapsed = int((monotonic() - stage_started) * 1000)
            elapsed = int((monotonic() - started) * 1000)
            return DevelopmentJobRunResponse(
                run_id=run_id,
                job_id=job_id,
                job_type=claimed.job_type,
                status="failed",
                started_at=started_at,
                duration_ms=elapsed,
                stages=[
                    DevelopmentRunStage(
                        name=stage_name,
                        status="failed",
                        duration_ms=stage_elapsed,
                        result={"error_code": error_code, "retryable": retryable},
                    )
                ],
                failed_stage=stage_name,
                warnings=["Job 오류 상세는 서버 Job 상태에서 확인할 수 있습니다."],
            )

        stage_elapsed = int((monotonic() - stage_started) * 1000)
        elapsed = int((monotonic() - started) * 1000)
        return DevelopmentJobRunResponse(
            run_id=run_id,
            job_id=job_id,
            job_type=claimed.job_type,
            status="completed",
            started_at=started_at,
            duration_ms=elapsed,
            stages=[
                DevelopmentRunStage(
                    name=stage_name,
                    status="completed",
                    duration_ms=stage_elapsed,
                    result=result,
                )
            ],
            result=result,
        )
