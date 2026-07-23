"""개발용 Agent 동기 실행 API의 요청과 응답 스키마.

운영 비동기 계약을 바꾸지 않고 Swagger에서 Job Handler와 Wiki Builder를
즉시 실행할 때 사용하는 명시적인 개발 전용 모델을 제공한다.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.latest_information import (
    LatestInformationItem,
    LatestInformationSearchRequest,
    LatestProviderFailure,
    LatestProviderName,
)
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


class PendingWikiBuildRunRequest(DevelopmentSchema):
    """사용자의 실행 가능한 Wiki Build Job Batch 실행 요청."""

    limit: int = Field(
        default=10, ge=1, le=20, description="한 번에 실행할 최대 Job 수"
    )


class UrlCollectionWorkerRunRequest(DevelopmentSchema):
    """등록된 URL 원본의 대기 수집 Job을 Worker 방식으로 실행하는 요청."""

    user_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="특정 사용자 Job만 실행할 때 지정. 생략하면 전체 사용자 대상",
    )
    limit: int = Field(
        default=10, ge=1, le=20, description="한 번에 실행할 최대 Job 수"
    )


class DevelopmentWorkerJobResult(DevelopmentSchema):
    """Worker Batch 실행이 처리한 Job 하나의 결과."""

    job_id: str = Field(description="처리한 Agent Job ID")
    status: Literal["completed", "failed", "skipped"] = Field(
        description="Job 처리 상태"
    )
    error_code: str | None = Field(
        default=None, description="건너뛰거나 실패한 Job의 오류 코드"
    )
    run: DevelopmentJobRunResponse | None = Field(
        default=None, description="실행한 Job의 단계별 결과. 건너뛴 Job은 null"
    )


class DevelopmentWorkerRunResponse(DevelopmentSchema):
    """실행 가능한 Job Batch를 Worker 방식으로 처리한 집계 결과."""

    run_id: str = Field(description="Batch 실행 추적 ID")
    job_type: str = Field(description="실행한 Job 유형")
    user_id: str | None = Field(default=None, description="Job을 필터링한 사용자 ID")
    started_at: datetime = Field(description="Batch 실행 시작 시각")
    duration_ms: int = Field(ge=0, description="전체 처리 시간")
    pending_count: int = Field(ge=0, description="조회된 실행 가능 Job 수")
    completed_count: int = Field(ge=0, description="완료된 Job 수")
    failed_count: int = Field(ge=0, description="실패한 Job 수")
    skipped_count: int = Field(ge=0, description="경합 등으로 건너뛴 Job 수")
    items: list[DevelopmentWorkerJobResult] = Field(
        default_factory=list, description="Job별 처리 결과"
    )


class LatestNewsWorkerRunRequest(DevelopmentSchema):
    """[미구현] 최신 뉴스 수집 Worker 실행 요청."""

    providers: list[LatestProviderName] = Field(
        default_factory=lambda: ["gdelt"],
        min_length=1,
        max_length=4,
        description="뉴스를 수집할 외부 Provider 목록",
    )
    keywords: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="수집 키워드. 비어 있으면 사용자 활성 관심 키워드를 사용",
    )
    limit_per_provider: int = Field(
        default=10, ge=1, le=50, description="Provider별 최대 수집 기사 수"
    )


class LatestNewsWorkerRunResponse(DevelopmentSchema):
    """[미구현] 최신 뉴스 수집 Worker 실행 결과 계약."""

    run_id: str = Field(description="Worker 실행 추적 ID")
    status: Literal["completed", "failed"] = Field(description="Worker 실행 상태")
    keywords: list[str] = Field(description="수집에 사용한 키워드")
    collected_count: int = Field(ge=0, description="Provider에서 수집한 기사 수")
    stored_count: int = Field(ge=0, description="Global 문서로 저장한 기사 수")
    items: list[LatestInformationItem] = Field(
        default_factory=list, description="저장된 최신 Global 문서"
    )
    provider_failures: list[LatestProviderFailure] = Field(
        default_factory=list, description="부분 실패 Provider 목록"
    )


class WikiKeywordLatestInformationRequest(DevelopmentSchema):
    """[미구현] Wiki 연결 상위 Node 키워드로 최신 정보를 검색하는 요청."""

    node_limit: int = Field(
        default=5, ge=1, le=20, description="키워드로 사용할 연결 상위 Node 수"
    )
    providers: list[LatestProviderName] = Field(
        default_factory=lambda: ["gdelt"],
        min_length=1,
        max_length=4,
        description="검색할 외부 Provider 목록",
    )
    language: str | None = Field(
        default=None, min_length=2, max_length=16, description="검색 언어"
    )
    limit_per_provider: int = Field(
        default=10, ge=1, le=50, description="Provider별 최대 결과 수"
    )


class WikiKeywordLatestInformationResponse(DevelopmentSchema):
    """[미구현] Wiki 상위 Node 키워드 최신 정보 검색·저장 결과 계약."""

    run_id: str = Field(description="검색 실행 추적 ID")
    user_id: str = Field(description="검색 기준 사용자 ID")
    keywords: list[str] = Field(description="연결 상위 Node에서 만든 검색 키워드")
    items: list[LatestInformationItem] = Field(
        default_factory=list, description="저장된 최신 Global 문서"
    )
    provider_failures: list[LatestProviderFailure] = Field(
        default_factory=list, description="부분 실패 Provider 목록"
    )


class InsightGenerationRequest(DevelopmentSchema):
    """[미구현] 개인 Wiki와 최신 정보로 요약·인사이트 콘텐츠를 생성하는 요청."""

    idempotency_key: str = Field(
        min_length=1, max_length=128, description="중복 생성을 막는 요청 멱등성 키"
    )
    topic: str | None = Field(
        default=None,
        max_length=500,
        description="생성 주제. 비어 있으면 연결 상위 Node 키워드로 구성",
    )
    language: str = Field(
        default="ko", min_length=2, max_length=16, description="생성 언어"
    )
    latest_limit: int = Field(
        default=10, ge=1, le=50, description="참고할 최신 Global 문서 수"
    )


class InsightGenerationResponse(DevelopmentSchema):
    """[미구현] 요약·인사이트 콘텐츠 생성 결과 계약."""

    run_id: str = Field(description="생성 실행 추적 ID")
    content_candidate_id: str = Field(description="저장된 생성 후보 UUID")
    title: str = Field(description="생성 콘텐츠 제목")
    summary: str = Field(description="핵심 요약")
    body: str = Field(description="요약과 인사이트 본문 Markdown")
    used_wiki_document_ids: list[str] = Field(
        default_factory=list, description="참고한 개인 Wiki 문서 ID"
    )
    used_latest_document_ids: list[str] = Field(
        default_factory=list, description="참고한 최신 Global 문서 ID"
    )


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
    """원본 저장부터 Report Builder 콘텐츠까지 한 번에 실행하는 개발 요청."""

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
    generation: GenerationRequest = Field(description="Report Builder 생성 조건")


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
