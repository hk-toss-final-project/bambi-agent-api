"""원본 입력부터 Report Builder 콘텐츠까지 실행하는 개발 시나리오 오케스트레이터.

운영 API가 쓰는 원본·Generation Job 접수와 공통 Job Handler를 순서대로 호출해
Swagger 한 요청으로 전체 영속 흐름을 검증한다.
"""

from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from app.exceptions import AgentApiError
from app.schemas.development import (
    DevelopmentRunStage,
    ScenarioUrlSource,
    SourceToContentScenarioRequest,
    SourceToContentScenarioResponse,
)
from app.schemas.mvp import UrlWikiSourceRequest, WebClippingRequest
from app.services.agent_workflows import AgentWorkflowService
from app.services.interests import InterestService
from app.services.latest_information import LatestInformationService
from app.services.mvp import AgentApiMvpService


class DevelopmentScenarioService:
    """개발용 Source-to-Content 전체 흐름을 단계별로 실행한다."""

    def __init__(
        self,
        jobs: AgentApiMvpService,
        workflows: AgentWorkflowService,
        interests: InterestService,
        latest_information: LatestInformationService,
    ) -> None:
        """운영 접수 서비스와 실제 Handler 기반 실행 서비스를 주입한다."""
        self._jobs = jobs
        self._workflows = workflows
        self._interests = interests
        self._latest_information = latest_information

    @staticmethod
    def _stage(
        name: str,
        started: float,
        *,
        status: str = "completed",
        result: dict[str, object] | None = None,
    ) -> DevelopmentRunStage:
        """현재 시각까지의 소요 시간을 포함한 시나리오 Stage를 만든다."""
        return DevelopmentRunStage(
            name=name,
            status=status,  # type: ignore[arg-type]
            duration_ms=int((monotonic() - started) * 1000),
            result=result or {},
        )

    @staticmethod
    def _failed_response(
        *,
        run_id: str,
        user_id: str,
        started_at: datetime,
        started: float,
        stages: list[DevelopmentRunStage],
        result: dict[str, object],
        failed_stage: str,
        error_code: str,
    ) -> SourceToContentScenarioResponse:
        """완료된 결과를 보존한 시나리오 실패 응답을 만든다."""
        if not stages or not (
            stages[-1].name == failed_stage and stages[-1].status == "failed"
        ):
            stages.append(
                DevelopmentRunStage(
                    name=failed_stage,
                    status="failed",
                    duration_ms=0,
                    result={"error_code": error_code},
                )
            )
        return SourceToContentScenarioResponse(
            run_id=run_id,
            user_id=user_id,
            status="failed",
            started_at=started_at,
            duration_ms=int((monotonic() - started) * 1000),
            stages=stages,
            result=result,
            failed_stage=failed_stage,
        )

    async def run(
        self,
        user_id: str,
        payload: SourceToContentScenarioRequest,
        *,
        request_id: str,
    ) -> SourceToContentScenarioResponse:
        """Context·원본·Wiki·관심·최신 정보·Report Builder 순서로 전체 흐름을 실행한다."""
        run_id = str(uuid4())
        started_at = datetime.now(UTC)
        started = monotonic()
        stages: list[DevelopmentRunStage] = []
        result: dict[str, object] = {}
        current_stage = "context"
        try:
            if payload.context is not None:
                stage_started = monotonic()
                context = await self._jobs.upsert_user_context(
                    user_id,
                    payload.context,
                    request_id,
                )
                result["context_version"] = context.context_version
                stages.append(
                    self._stage(
                        "context",
                        stage_started,
                        result={"context_version": context.context_version},
                    )
                )

            current_stage = "source_ingestion"
            stage_started = monotonic()
            if isinstance(payload.source, ScenarioUrlSource):
                source_payload = UrlWikiSourceRequest.model_validate(
                    payload.source.model_dump(exclude={"type"})
                )
                accepted = await self._jobs.submit_url_source(
                    user_id=user_id,
                    payload=source_payload,
                    request_id=request_id,
                )
            else:
                source_payload = WebClippingRequest.model_validate(
                    payload.source.model_dump(exclude={"type"})
                )
                accepted = await self._jobs.submit_web_clipping(
                    user_id=user_id,
                    payload=source_payload,
                    request_id=request_id,
                )
            result.update(
                {
                    "source_document_id": accepted.source_document_id,
                    "source_document_version_id": accepted.source_document_version_id,
                    "source_job_id": accepted.job_id,
                }
            )
            stages.append(
                self._stage(
                    current_stage,
                    stage_started,
                    result={"job_id": accepted.job_id},
                )
            )

            wiki_job_id = accepted.job_id
            if isinstance(payload.source, ScenarioUrlSource):
                current_stage = "url_collection"
                url_run = await self._workflows.run_job(
                    accepted.job_id,
                    expected_job_type="personal_wiki_url",
                    expected_user_id=user_id,
                )
                stages.extend(url_run.stages)
                if url_run.status == "failed":
                    return self._failed_response(
                        run_id=run_id,
                        user_id=user_id,
                        started_at=started_at,
                        started=started,
                        stages=stages,
                        result=result,
                        failed_stage=url_run.failed_stage or current_stage,
                        error_code="URL_COLLECTION_FAILED",
                    )
                result.update(url_run.result)
                next_job = url_run.result.get("wiki_build_job_id")
                wiki_job_id = str(next_job) if next_job else ""

            if wiki_job_id:
                current_stage = "wiki_build"
                wiki_run = await self._workflows.run_job(
                    wiki_job_id,
                    expected_job_type="personal_wiki_build",
                    expected_user_id=user_id,
                )
                stages.extend(wiki_run.stages)
                if wiki_run.status == "failed":
                    return self._failed_response(
                        run_id=run_id,
                        user_id=user_id,
                        started_at=started_at,
                        started=started,
                        stages=stages,
                        result=result,
                        failed_stage=wiki_run.failed_stage or current_stage,
                        error_code="WIKI_BUILD_FAILED",
                    )
                result.update(wiki_run.result)

            current_stage = "interest_extraction"
            stage_started = monotonic()
            profile = await self._interests.rebuild(
                user_id, limit=payload.interest_limit
            )
            result["interest_profile_id"] = profile.profile_id
            stages.append(
                self._stage(
                    current_stage,
                    stage_started,
                    result={
                        "profile_id": profile.profile_id,
                        "interest_count": len(profile.interests),
                    },
                )
            )

            current_stage = "latest_collection"
            stage_started = monotonic()
            latest = await self._latest_information.search(user_id, payload.latest)
            result["latest_document_version_ids"] = [
                item.document_version_id for item in latest.items
            ]
            stages.append(
                self._stage(
                    current_stage,
                    stage_started,
                    result={
                        "document_count": len(latest.items),
                        "provider_failures": len(latest.provider_failures),
                    },
                )
            )

            current_stage = "report_generation"
            accepted_generation = await self._jobs.submit_generation(
                user_id=user_id,
                payload=payload.generation,
                request_id=request_id,
            )
            result["generation_job_id"] = accepted_generation.job_id
            report_run = await self._workflows.run_job(
                accepted_generation.job_id,
                expected_job_type="report_generation",
                expected_user_id=user_id,
            )
            stages.extend(report_run.stages)
            if report_run.status == "failed":
                return self._failed_response(
                    run_id=run_id,
                    user_id=user_id,
                    started_at=started_at,
                    started=started,
                    stages=stages,
                    result=result,
                    failed_stage=report_run.failed_stage or current_stage,
                    error_code="REPORT_GENERATION_FAILED",
                )
            result.update(report_run.result)
        except AgentApiError as error:
            return self._failed_response(
                run_id=run_id,
                user_id=user_id,
                started_at=started_at,
                started=started,
                stages=stages,
                result=result,
                failed_stage=current_stage,
                error_code=error.detail.code,
            )

        return SourceToContentScenarioResponse(
            run_id=run_id,
            user_id=user_id,
            status="completed",
            started_at=started_at,
            duration_ms=int((monotonic() - started) * 1000),
            stages=stages,
            result=result,
        )
