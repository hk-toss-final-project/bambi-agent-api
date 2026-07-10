"""FastAPI MVP 내부 API에서 사용하는 요청과 응답 스키마."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ImmutableSchema(BaseModel):
    """응답과 저장 레코드가 요청 처리 중 변경되지 않도록 하는 기본 모델."""

    model_config = ConfigDict(frozen=True)


class UserPlan(StrEnum):
    """MVP에서 지원하는 사용자 플랜 종류."""

    FREE = "free"
    PAID = "paid"


class JobStatus(StrEnum):
    """비동기 Agent Job의 처리 상태."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PublishStatus(StrEnum):
    """Service Worker가 전달하는 발행 처리 결과."""

    PUBLISHED = "published"
    FAILED = "failed"


class HealthResponse(ImmutableSchema):
    """Liveness와 Readiness 상태 응답."""

    status: str = Field(description="현재 상태")
    checks: dict[str, bool] = Field(default_factory=dict, description="컴포넌트별 상태")


class VersionResponse(ImmutableSchema):
    """Agent API와 실행 환경 버전 응답."""

    name: str = Field(description="애플리케이션 이름")
    version: str = Field(description="애플리케이션 버전")
    environment: str = Field(description="실행 환경")


class UserContextUpsertRequest(ImmutableSchema):
    """Service API가 전달하는 최소 사용자 컨텍스트."""

    context_version: int = Field(ge=1, description="단조 증가하는 컨텍스트 버전")
    plan: UserPlan = Field(description="사용자 플랜")
    preferred_language: str = Field(
        default="ko", min_length=2, max_length=16, description="선호 콘텐츠 언어"
    )
    personalization_enabled: bool = Field(
        default=True, description="개인화 기능 사용 여부"
    )
    blocked_interest_ids: list[str] = Field(
        default_factory=list, description="차단한 관심사 식별자 목록"
    )
    blocked_source_ids: list[str] = Field(
        default_factory=list, description="차단한 Source 식별자 목록"
    )


class UserContextResponse(ImmutableSchema):
    """저장된 사용자 컨텍스트와 추적 정보."""

    feature_id: str = Field(default="SVC-001", description="명세 기능 ID")
    user_id: str = Field(description="사용자 식별자")
    context_version: int = Field(description="반영된 컨텍스트 버전")
    plan: UserPlan = Field(description="반영된 사용자 플랜")
    preferred_language: str = Field(description="반영된 선호 언어")
    personalization_enabled: bool = Field(description="개인화 사용 여부")
    blocked_interest_ids: list[str] = Field(description="차단 관심사 목록")
    blocked_source_ids: list[str] = Field(description="차단 Source 목록")
    updated_at: datetime = Field(description="컨텍스트 갱신 시각")
    request_id: str = Field(description="요청 추적 ID")


class WikiSourceRequestBase(ImmutableSchema):
    """개인 Wiki 원천 처리 요청의 공통 필드."""

    source_event_id: str = Field(
        min_length=1, max_length=128, description="멱등 처리를 위한 원천 이벤트 ID"
    )
    occurred_at: datetime | None = Field(
        default=None, description="사용자 행동 발생 시각"
    )
    memo: str | None = Field(default=None, max_length=4000, description="사용자 메모")


class WebClippingRequest(WikiSourceRequestBase):
    """웹 클리핑을 개인 Wiki 처리 작업으로 전달하는 요청."""

    url: HttpUrl = Field(description="클리핑 원문 URL")
    title: str = Field(min_length=1, max_length=500, description="클리핑 제목")
    content: str = Field(min_length=1, description="클리핑 본문")


class UrlWikiSourceRequest(WikiSourceRequestBase):
    """사용자가 입력한 URL을 개인 Wiki 처리 작업으로 전달하는 요청."""

    url: HttpUrl = Field(description="개인 Wiki에 반영할 URL")


class ContentMarkRequest(WikiSourceRequestBase):
    """생성 콘텐츠의 위키마킹 처리를 요청하는 모델."""

    content_id: str = Field(min_length=1, max_length=128, description="생성 콘텐츠 ID")


class GenerationRequest(ImmutableSchema):
    """밤비 개인화 콘텐츠 생성을 요청하는 모델."""

    idempotency_key: str = Field(
        min_length=1, max_length=128, description="중복 생성을 방지하는 요청 키"
    )
    topic: str = Field(min_length=1, max_length=500, description="생성할 콘텐츠 주제")
    content_type: str = Field(
        default="interest_news_card",
        min_length=1,
        max_length=64,
        description="생성 콘텐츠 유형",
    )
    language: str | None = Field(
        default=None, min_length=2, max_length=16, description="요청 콘텐츠 언어"
    )


class AcceptedJobResponse(ImmutableSchema):
    """비동기 작업 접수 결과."""

    job_id: str = Field(description="Agent Job 식별자")
    feature_id: str = Field(description="작업을 생성한 명세 기능 ID")
    status: JobStatus = Field(description="현재 작업 상태")
    request_id: str = Field(description="요청 추적 ID")
    created_at: datetime = Field(description="작업 생성 시각")


class JobStatusResponse(AcceptedJobResponse):
    """Agent Job 상태와 진행률 응답."""

    user_id: str = Field(description="작업 대상 사용자 ID")
    job_type: str = Field(description="Worker가 처리할 작업 유형")
    progress: int = Field(default=0, ge=0, le=100, description="작업 진행률")
    updated_at: datetime = Field(description="마지막 상태 변경 시각")
    error_code: str | None = Field(default=None, description="실패 오류 코드")


class JobResultResponse(ImmutableSchema):
    """완료된 Agent Job 결과 응답."""

    job_id: str = Field(description="Agent Job 식별자")
    feature_id: str = Field(description="원본 명세 기능 ID")
    status: JobStatus = Field(description="완료 작업 상태")
    result: dict[str, object] = Field(description="기능별 작업 결과")
    completed_at: datetime = Field(description="작업 완료 시각")


class CitationSchema(ImmutableSchema):
    """발행 Snapshot에 포함되는 출처 정보."""

    citation_id: str = Field(description="Citation 식별자")
    title: str = Field(description="출처 제목")
    url: str = Field(description="출처 URL")


class PublishSnapshotResponse(ImmutableSchema):
    """Service Worker가 service-db에 저장할 발행 Snapshot."""

    content_id: str = Field(description="생성 콘텐츠 식별자")
    user_id: str = Field(description="콘텐츠 대상 사용자 ID")
    version: int = Field(ge=1, description="콘텐츠 버전")
    snapshot_hash: str = Field(description="Snapshot 무결성 Hash")
    title: str = Field(description="콘텐츠 제목")
    summary: str = Field(description="피드용 콘텐츠 요약")
    body: str = Field(description="발행 콘텐츠 본문")
    citations: list[CitationSchema] = Field(
        default_factory=list, description="본문과 연결된 출처 목록"
    )
    created_at: datetime = Field(description="Snapshot 생성 시각")


class PublishAckRequest(ImmutableSchema):
    """Service Worker가 전달하는 발행 완료 또는 실패 ACK."""

    version: int = Field(ge=1, description="반영한 콘텐츠 버전")
    snapshot_hash: str = Field(min_length=1, description="반영한 Snapshot Hash")
    status: PublishStatus = Field(description="service-db 반영 결과")
    failure_reason: str | None = Field(
        default=None, max_length=2000, description="발행 실패 사유"
    )

    @model_validator(mode="after")
    def validate_failure_reason(self) -> "PublishAckRequest":
        """발행 실패 ACK에 실패 사유가 포함되었는지 검증한다."""
        if self.status is PublishStatus.FAILED and not self.failure_reason:
            raise ValueError("발행 실패 시 failure_reason이 필요합니다.")
        return self


class PublishAckResponse(ImmutableSchema):
    """Agent API가 ACK를 반영한 결과."""

    feature_id: str = Field(default="SW-009", description="명세 기능 ID")
    content_id: str = Field(description="생성 콘텐츠 식별자")
    version: int = Field(description="반영된 콘텐츠 버전")
    status: PublishStatus = Field(description="반영된 발행 상태")
    acknowledged_at: datetime = Field(description="ACK 반영 시각")
