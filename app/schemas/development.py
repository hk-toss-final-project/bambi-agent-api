"""개발용 Agent 동기 실행 API의 요청과 응답 스키마.

운영 비동기 계약을 바꾸지 않고 Swagger에서 Job Handler와 Wiki Builder를
즉시 실행할 때 사용하는 명시적인 개발 전용 모델을 제공한다.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.latest_information import LatestInformationSearchRequest
from app.schemas.mvp import (
    GenerationRequest,
    UrlWikiSourceRequest,
    UserContextUpsertRequest,
    WebClippingRequest,
)


class DevelopmentSchema(BaseModel):
    """개발 API 모델이 요청 처리 중 변경되지 않게 하는 공통 기반."""

    model_config = ConfigDict(frozen=True)


class WikiBuildRunRequest(DevelopmentSchema):
    """접수된 Personal Wiki Build Job을 즉시 실행하는 요청."""

    job_id: str = Field(
        min_length=1,
        max_length=128,
        description="personal_wiki_build 유형의 Agent Job ID",
    )


class DevelopmentRunStage(DevelopmentSchema):
    """개발용 동기 실행에서 처리한 한 단계의 결과."""

    name: str = Field(description="실행 단계 이름")
    status: Literal["completed", "failed", "skipped"] = Field(
        description="단계 처리 상태"
    )
    duration_ms: int = Field(ge=0, description="단계 처리 시간")
    result: dict[str, object] = Field(
        default_factory=dict, description="비밀정보를 제외한 단계 결과"
    )


class DevelopmentJobRunResponse(DevelopmentSchema):
    """개발 환경에서 Agent Job을 즉시 실행한 결과."""

    run_id: str = Field(description="동기 실행 추적 ID")
    job_id: str = Field(description="실행한 Agent Job ID")
    job_type: str = Field(description="실행한 Job 유형")
    status: Literal["completed", "failed"] = Field(description="최종 실행 상태")
    started_at: datetime = Field(description="실행 시작 시각")
    duration_ms: int = Field(ge=0, description="전체 처리 시간")
    stages: list[DevelopmentRunStage] = Field(description="단계별 실행 결과")
    result: dict[str, object] = Field(
        default_factory=dict, description="영속화된 최종 결과와 후속 Job ID"
    )
    failed_stage: str | None = Field(default=None, description="실패한 단계")
    warnings: list[str] = Field(default_factory=list, description="실행 경고")


class ScenarioWebClippingSource(WebClippingRequest):
    """전체 시나리오에 직접 전달하는 Markdown 웹 클리핑 원본."""

    type: Literal["clipping"] = Field(default="clipping", description="원본 유형")


class ScenarioUrlSource(UrlWikiSourceRequest):
    """전체 시나리오에서 Jina Reader로 수집할 URL 원본."""

    type: Literal["url"] = Field(default="url", description="원본 유형")


ScenarioSource = Annotated[
    ScenarioWebClippingSource | ScenarioUrlSource,
    Field(discriminator="type"),
]


class SourceToContentScenarioRequest(DevelopmentSchema):
    """원본 저장부터 Bambi 콘텐츠까지 한 번에 실행하는 개발 요청."""

    source: ScenarioSource = Field(description="URL 또는 Markdown 클리핑 원본")
    context: UserContextUpsertRequest | None = Field(
        default=None,
        description="함께 반영할 사용자 Context. 생략하면 기존 최신 Context 사용",
    )
    interest_limit: int = Field(
        default=20, ge=1, le=100, description="계산할 최대 관심 Topic 수"
    )
    latest: LatestInformationSearchRequest = Field(
        default_factory=LatestInformationSearchRequest,
        description="최신 외부 정보 검색 조건",
    )
    generation: GenerationRequest = Field(description="Bambi 생성 조건")


class SourceToContentScenarioResponse(DevelopmentSchema):
    """원본에서 생성 콘텐츠까지 실행한 단계별 개발 시나리오 결과."""

    run_id: str = Field(description="전체 시나리오 실행 ID")
    user_id: str = Field(description="실행 대상 사용자 ID")
    status: Literal["completed", "failed"] = Field(description="시나리오 최종 상태")
    started_at: datetime = Field(description="시나리오 시작 시각")
    duration_ms: int = Field(ge=0, description="전체 실행 시간")
    stages: list[DevelopmentRunStage] = Field(description="완료·실패 단계 목록")
    result: dict[str, object] = Field(
        default_factory=dict, description="단계별 영속 결과 식별자"
    )
    failed_stage: str | None = Field(default=None, description="실패한 단계")
