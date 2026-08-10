"""개발 API와 운영 Worker가 공유할 Agent Job 실행기.

Job 유형에 따라 URL 수집 또는 LangGraph 오케스트레이션(Wiki Build,
Report Builder Generation)을 실행하고, Lease·완료·실패 상태를 저장한 뒤
Swagger용 단계 결과를 반환한다.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from fastapi import status

from agent.graph import run_report_generation, run_personal_wiki_build
from agent.report_builder.api import report_001
from agent.wiki_builder.api import wba_001
from app.config import Settings
from app.exceptions import AgentApiError, ErrorDetail
from app.schemas.development import (
    DevelopmentJobRunResponse,
    DevelopmentRunStage,
    DevelopmentWorkerJobResult,
    DevelopmentWorkerRunResponse,
)
from app.services.agent_jobs import AgentJobRepository, ClaimedJobRecord
from domain.jobs.api import job_007
from infrastructure.sources.connectors.api import (
    JinaReadError,
    JinaReadResult,
    fetch_url_via_jina,
)
from shared.contracts import FeatureRequest

type UrlFetcher = Callable[[str], JinaReadResult]
type WikiRunner = Callable[..., Awaitable[dict[str, object]]]
type ReportRunner = Callable[..., Awaitable[dict[str, object]]]


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
        wiki_runner: WikiRunner = run_personal_wiki_build,
        report_runner: ReportRunner = run_report_generation,
    ) -> None:
        """Job 저장소, 모델 설정, URL 수집기와 그래프 실행기를 주입한다."""
        self._repository = repository
        self._settings = settings
        self._url_fetcher = url_fetcher
        self._wiki_runner = wiki_runner
        self._report_runner = report_runner

    async def _dispatch(self, job: ClaimedJobRecord) -> tuple[str, dict[str, object]]:
        """Job 유형에 맞는 URL 수집 또는 LangGraph 오케스트레이션을 실행한다."""
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
            source_version_id = str(
                job.payload.get("source_document_version_id") or ""
            )
            if not source_version_id:
                raise ValueError("Wiki Build Job Payload에 원본 Version ID가 없습니다.")
            async with self._repository.acquire_connection() as connection:
                result = await wba_001(
                    self._wiki_runner,
                    connection,
                    user_id=job.user_id,
                    source_document_version_id=source_version_id,
                    job_id=job.job_id,
                    model=self._settings.wiki_llm_model,
                )
            return "wiki_build", result
        if job.job_type == "report_generation":
            topic = str(job.payload.get("topic") or "").strip()
            topics = [
                str(value).strip()
                for value in (job.payload.get("topics") or [])
                if str(value).strip()
            ]
            content_type = str(job.payload.get("content_type") or "").strip()
            language = str(job.payload.get("language") or "ko").strip()
            if not topic or not content_type:
                raise ValueError("Report Builder Job Payload에 topic과 content_type이 필요합니다.")
            # 변경점 추적 토글. 이 키가 없는 기존 Job(플래그 도입 이전 등록분)은
            # 지금까지와 같은 생성 경로로 실행된다.
            change_history_enabled = bool(
                job.payload.get("change_history_enabled") or False
            )
            generation_scope = str(
                job.payload.get("generation_scope") or "SINGLE_TOPIC"
            )
            raw_interest_bundle = job.payload.get("interest_bundle")
            interest_bundle = (
                dict(raw_interest_bundle)
                if isinstance(raw_interest_bundle, dict)
                else None
            )
            if generation_scope == "INTEREST_BUNDLE" and interest_bundle is None:
                raise ValueError("INTEREST_BUNDLE Job Payload에 interest_bundle이 필요합니다.")
            raw_topic_interest_bundles = job.payload.get("topic_interest_bundles")
            topic_interest_bundles = (
                {
                    str(key): dict(value)
                    for key, value in raw_topic_interest_bundles.items()
                    if isinstance(value, dict)
                }
                if isinstance(raw_topic_interest_bundles, dict)
                else {}
            )
            async with self._repository.acquire_connection() as connection:
                feature_result = await report_001(
                    FeatureRequest(
                        request_id=job.job_id,
                        actor_id="development-agent-workflow",
                        user_id=job.user_id,
                        payload={
                            "implementation": lambda: self._report_runner(
                                connection,
                                user_id=job.user_id,
                                job_id=job.job_id,
                                attempt_number=job.attempt_number,
                                topic=topic,
                                topics=topics,
                                content_type=content_type,
                                language=language,
                                model=self._settings.report_llm_model,
                                change_history_enabled=change_history_enabled,
                                generation_scope=generation_scope,
                                interest_bundle=interest_bundle,
                                topic_interest_bundles=topic_interest_bundles,
                            )
                        },
                    )
                )
            return "report_generation", dict(feature_result.data)
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
                linked_result = await job_007(result)
                await self._repository.complete_job(
                    job=claimed,
                    worker_id=worker_id,
                    result=linked_result,
                )
                result = linked_result
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

    async def run_pending_jobs(
        self,
        *,
        job_type: str,
        user_id: str | None = None,
        limit: int = 10,
    ) -> DevelopmentWorkerRunResponse:
        """실행 가능한 Job Batch를 조회해 순서대로 실행하고 집계를 반환한다.

        운영 Worker와 같은 실행 가능 조건(queued 또는 Lease 만료, scheduled_at
        도래)으로 Job을 조회하되, 각 Job은 run_job과 동일한 Claim·Handler·완료
        경로로 한 건씩 실행한다. 다른 Worker가 먼저 점유한 Job은 Batch를
        중단하지 않고 skipped로 기록한다.

        Args:
            job_type: 실행할 Job 유형 (personal_wiki_build, personal_wiki_url 등)
            user_id: 특정 사용자의 Job만 실행할 때 지정
            limit: 한 번에 실행할 최대 Job 수

        Returns:
            Job별 실행 결과와 완료·실패·건너뜀 집계
        """
        started_at = datetime.now(UTC)
        started = monotonic()
        job_ids = await self._repository.list_runnable_jobs(
            job_type=job_type, user_id=user_id, limit=limit
        )
        items: list[DevelopmentWorkerJobResult] = []
        for job_id in job_ids:
            try:
                run = await self.run_job(
                    job_id,
                    expected_job_type=job_type,
                    expected_user_id=user_id,
                )
            except AgentApiError as error:
                items.append(
                    DevelopmentWorkerJobResult(
                        job_id=job_id,
                        status="skipped",
                        error_code=error.detail.code,
                    )
                )
                continue
            error_code: str | None = None
            if run.status == "failed" and run.stages:
                failed_code = run.stages[-1].result.get("error_code")
                error_code = str(failed_code) if failed_code else None
            items.append(
                DevelopmentWorkerJobResult(
                    job_id=job_id,
                    status=run.status,
                    error_code=error_code,
                    run=run,
                )
            )
        return DevelopmentWorkerRunResponse(
            run_id=str(uuid4()),
            job_type=job_type,
            user_id=user_id,
            started_at=started_at,
            duration_ms=int((monotonic() - started) * 1000),
            pending_count=len(job_ids),
            completed_count=sum(1 for item in items if item.status == "completed"),
            failed_count=sum(1 for item in items if item.status == "failed"),
            skipped_count=sum(1 for item in items if item.status == "skipped"),
            items=items,
        )
